import streamlit as st
import fitz  # PyMuPDF
import re
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import io
from PIL import Image, ImageOps # Adicionado ImageOps para o corte inteligente

# Configuração da Página
st.set_page_config(page_title="Gerador de Catálogo", layout="wide")

# --- FUNÇÃO AUXILIAR: PADRONIZAR IMAGEM (PREENCHIMENTO TOTAL) ---
def padronizar_imagem(image_bytes, size=(300, 300)):
    """
    Usa a técnica de 'Aspect Fill' (ImageOps.fit).
    A imagem é redimensionada para preencher TODO o quadrado,
    cortando o excesso centralizado (center crop).
    """
    try:
        if not image_bytes: return None
        
        # Abre a imagem original extraída do PDF
        img = Image.open(io.BytesIO(image_bytes))
        
        # ImageOps.fit redimensiona mantendo a proporção até preencher o tamanho,
        # e corta o que sobrar (Center Crop). Elimina espaços em branco.
        new_img = ImageOps.fit(img, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        
        # Garante que seja RGB (remove transparência para salvar em JPEG depois)
        if new_img.mode != 'RGB':
            new_img = new_img.convert('RGB')
        
        return new_img
    except Exception:
        return None

# --- 1. FUNÇÃO DE EXTRAÇÃO (HÍBRIDA: NATIVA -> FALLBACK PRINT HD) ---
def extract_products_from_pdf(uploaded_file):
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    products = []
    
    for page_num, page in enumerate(doc):
        text_blocks = page.get_text("blocks")
        
        # 1. Mapear ONDE as imagens estão e qual seu ID (xref)
        image_list = page.get_images(full=True)
        page_images_data = [] # Lista de tuplas (xref, rect)
        
        for img in image_list:
            xref = img[0]
            rects = page.get_image_rects(xref)
            if rects:
                for r in rects:
                    if r.width > 30 and r.height > 30: 
                        # Guardamos o XREF (para tentar extrair original) e o RECT (para printar se falhar)
                        page_images_data.append((xref, r))

        # 2. ACHAR AS ÂNCORAS (Os Preços)
        price_blocks = []
        for block in text_blocks:
            text = block[4].strip()
            if "R$" in text:
                price_blocks.append(block)

        # 3. MONTAR OS PRODUTOS
        for p_block in price_blocks:
            px0, py0, px1, py1, p_text, _, _ = p_block
            p_center_x = (px0 + px1) / 2
            p_center_y = (py0 + py1) / 2
            
            # --- A. ACHAR O NOME ---
            best_name = "Nome Desconhecido"
            min_dist_y = 9999
            
            for b in text_blocks:
                bx0, by0, bx1, by1, b_text, _, _ = b
                if b == p_block: continue
                
                if by1 <= py0 + 15: 
                    dist_y = py0 - by1
                    b_center_x = (bx0 + bx1) / 2
                    dist_x = abs(p_center_x - b_center_x)
                    
                    if dist_y < 80 and dist_x < 50:
                        if dist_y < min_dist_y:
                            min_dist_y = dist_y
                            best_name = b_text.strip().replace('\n', ' ')

            if "Estoque" in best_name: best_name = "Nome Indisponível"
            if best_name.endswith(" R"): best_name = best_name[:-2]

            # --- B. ACHAR A IMAGEM (HÍBRIDO) ---
            best_image_bytes = None
            best_img_id = f"no_img_{page_num}_{py0}"
            min_img_dist = 9999
            
            # Procura a imagem mais próxima
            for xref, rect in page_images_data:
                img_center_x = (rect.x0 + rect.x1) / 2
                img_center_y = (rect.y0 + rect.y1) / 2
                
                dist_x = abs(p_center_x - img_center_x)
                dist_y = abs(p_center_y - img_center_y)
                
                if dist_x < 50 and dist_y < 200:
                    if dist_y < min_img_dist:
                        min_img_dist = dist_y
                        best_img_id = f"img_{page_num}_{rect.y0}"
                        
                        # === ESTRATÉGIA HÍBRIDA ===
                        try:
                            # TENTATIVA 1: Extração Nativa (Melhor qualidade/Original)
                            raw_img = doc.extract_image(xref)
                            candidate_bytes = raw_img["image"]
                            
                            # Validação rigorosa: Tenta abrir com PIL
                            # Se for CMYK ou corrompida, o PIL vai reclamar ou mostrar modo estranho
                            img_check = Image.open(io.BytesIO(candidate_bytes))
                            img_check.verify() # Checa integridade do arquivo
                            
                            # Se passou na verificação, reabre para checar modo de cor
                            img_check = Image.open(io.BytesIO(candidate_bytes))
                            if img_check.mode == 'CMYK':
                                raise Exception("CMYK detectado - usar print")
                                
                            # Se chegou aqui, a imagem original é boa!
                            best_image_bytes = candidate_bytes
                            
                        except Exception:
                            # TENTATIVA 2 (FALLBACK): Print HD (Matrix 5x)
                            # Só entra aqui se a tentativa 1 falhou
                            try:
                                pix = page.get_pixmap(clip=rect, matrix=fitz.Matrix(5, 5), alpha=False, colorspace="rgb")
                                best_image_bytes = pix.tobytes("png")
                            except:
                                best_image_bytes = None

            # --- C. EXTRAIR VALORES ---
            price_match = re.search(r'R\$\s?([\d,.]+)', p_text)
            weight_match = re.search(r'\|\s?([\d,.]+)\s?g', p_text)
            
            price = price_match.group(1) if price_match else ""
            weight = weight_match.group(1) if weight_match else ""
            
            if len(price) > 0:
                products.append({
                    "id": best_img_id, 
                    "image_bytes": best_image_bytes,
                    "code": best_name if best_name != "Nome Desconhecido" else "Item s/ Nome",
                    "price": price,
                    "weight": weight,
                    "raw_text": p_text
                })

    return products

# --- 2. FUNÇÃO DE GERAÇÃO DO PDF (MANTIDA EM HD) ---
def generate_list_pdf(selected_items):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y_position = height - 50
    
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y_position, "Lista de Pedidos - Seleção")
    y_position -= 30
    
    c.setFont("Helvetica", 12)
    
    for item in selected_items:
        if y_position < 150:
            c.showPage()
            y_position = height - 50
        
        # Desenha Imagem
        if item["image_bytes"]:
            try:
                # Usa 1200px para garantir qualidade no PDF
                # ImageOps.fit vai garantir que o quadrado esteja CHEIO
                img_high_res = padronizar_imagem(item["image_bytes"], size=(1200, 1200))
                
                if img_high_res:
                    img_buffer = io.BytesIO()
                    img_high_res.save(img_buffer, format='JPEG', quality=100, subsampling=0)
                    img_buffer.seek(0)
                    
                    img = ImageReader(img_buffer)
                    c.drawImage(img, 50, y_position - 100, width=100, height=100, preserveAspectRatio=True, mask='auto')
                else:
                    raise Exception("Erro padronização")
            except:
                c.rect(50, y_position - 100, 100, 100)
                c.drawString(60, y_position - 50, "Erro Foto")
        else:
            c.rect(50, y_position - 100, 100, 100)
            c.drawString(60, y_position - 50, "Sem Foto")
            
        # Desenha Texto
        c.setFont("Helvetica-Bold", 12)
        c.drawString(170, y_position - 30, f"Ref: {item['code']}")
        
        c.setFont("Helvetica", 12)
        c.drawString(170, y_position - 50, f"Preço: {item['price']}")
        c.drawString(170, y_position - 70, f"Peso: {item['weight']}")

        # --- LINHA DIVISÓRIA  ---
        c.setStrokeColorRGB(0.7, 0.7, 0.7) # Cor cinza suave
        # Desenha linha de X=50 até X=(Largura da pág - 50)
        c.line(50, y_position - 110, width - 50, y_position - 110)
        c.setStrokeColorRGB(0, 0, 0) # Volta para preto para o próximo texto
        
        y_position -= 120 
        
    c.save()
    buffer.seek(0)
    return buffer

# --- 3. INTERFACE STREAMLIT ---
st.title("💎 Gerador de Catálogo Inteligente")
st.markdown("Faça upload do seu PDF, selecione os produtos e gere uma lista limpa.")

uploaded_pdf = st.file_uploader("Escolha o arquivo PDF", type="pdf")

if "products" not in st.session_state:
    st.session_state.products = []
if "pdf_buffer" not in st.session_state:
    st.session_state.pdf_buffer = None

if uploaded_pdf:
    if st.button("Processar PDF"):
        # Limpa estados anteriores
        st.session_state.products = []
        st.session_state.pdf_buffer = None
        
        with st.spinner("Processando PDF. Isso pode demorar alguns segundos..."):
            try:
                st.session_state.products = extract_products_from_pdf(uploaded_pdf)
                if not st.session_state.products:
                    st.error("Nenhum produto encontrado! Verifique se o PDF tem texto selecionável.")
                else:
                    st.success(f"{len(st.session_state.products)} produtos encontrados!")
            except Exception as e:
                st.error(f"Erro fatal ao processar: {e}")

    # Exibição dos Resultados
    if st.session_state.products:
        st.divider()
        st.subheader("Selecione os itens para a lista:")
        
        with st.form("my_form"):
            cols = st.columns(4)
            selected_indices = []
            
            for index, item in enumerate(st.session_state.products):
                col = cols[index % 4]
                with col:
                    # 1. IMAGEM LEVE PARA TELA (300px)
                    if item["image_bytes"]:
                        img_screen = padronizar_imagem(item["image_bytes"], size=(300, 300))
                        if img_screen:
                            st.image(img_screen, use_container_width=True)
                        else:
                            st.image("https://placehold.co/300x300?text=Erro", use_container_width=True)
                    else:
                        st.image("https://placehold.co/300x300?text=Sem+Foto", use_container_width=True)

                    # 2. TEXTO FORMATADO E TRAVADO
                    st.markdown(
                        f"""
                        <div style="height: 45px; overflow: hidden; display: flex; align-items: flex-start;">
                            <span style="font-weight: bold; font-size: 14px; line-height: 1.2;">{item['code']}</span>
                        </div>
                        """, 
                        unsafe_allow_html=True
                    )
                    
                    st.markdown(
                        f"""
                        <div style="height: 25px; color: #555; font-size: 13px;">
                            💰 {item['price']} | ⚖️ {item['weight']}
                        </div>
                        """, 
                        unsafe_allow_html=True
                    )
                    
                    # Checkbox com chave única
                    unique_key = f"chk_{index}_{str(item['code']).replace(' ', '_')}"
                    is_selected = st.checkbox("Selecionar", key=unique_key)
                    
                    if is_selected:
                        selected_indices.append(index)
            
            st.divider()
            submitted = st.form_submit_button("Gerar PDF com Itens Selecionados")
        
        if submitted:
            if not selected_indices:
                st.warning("⚠️ Você precisa marcar pelo menos um produto!")
            else:
                with st.spinner("Gerando PDF em Alta Resolução..."):
                    selected_items = [st.session_state.products[i] for i in selected_indices]
                    st.session_state.pdf_buffer = generate_list_pdf(selected_items)
                st.success("✅ PDF Criado com Sucesso!")

        if st.session_state.pdf_buffer is not None:
            st.markdown("---")
            col_left, col_center, col_right = st.columns([1, 2, 1])
            
            nome_original = uploaded_pdf.name.replace(".pdf", "")
            nome_final = f"{nome_original}_Selecionadas.pdf"
            
            with col_center:
                st.download_button(
                    label="📥 CLIQUE AQUI PARA BAIXAR O ARQUIVO",
                    data=st.session_state.pdf_buffer,
                    file_name=nome_final,
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True
                )