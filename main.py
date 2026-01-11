import streamlit as st
import fitz  # PyMuPDF
import re
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import io

# Configuração da Página
st.set_page_config(page_title="Gerador de Catálogo", layout="wide")

# --- 1. FUNÇÃO DE EXTRAÇÃO ---
def extract_products_from_pdf(uploaded_file):
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    products = []
    
    for page_num, page in enumerate(doc):
        # 1. Mapear todos os blocos de texto com suas coordenadas
        # blocks = (x0, y0, x1, y1, text, ...)
        text_blocks = page.get_text("blocks")
        
        # 2. Mapear todas as imagens com suas coordenadas
        image_list = page.get_images(full=True)
        page_images = []
        for img in image_list:
            xref = img[0]
            rects = page.get_image_rects(xref)
            if rects:
                # Considera a maior ocorrência da imagem (evita ícones duplicados)
                r = max(rects, key=lambda x: x.width * x.height)
                if r.width > 50 and r.height > 50: # Filtra sujeira
                    page_images.append((xref, r))

        # 3. ACHAR AS ÂNCORAS (Os Preços)
        # O preço é o ponto central do card. Procuramos blocos com "R$" e "g"
        price_blocks = []
        for block in text_blocks:
            text = block[4].strip()
            # Limpeza básica para garantir match
            if "R$" in text and "g" in text:
                price_blocks.append(block)

        # 4. MONTAR OS PRODUTOS BASEADO NAS ÂNCORAS
        for p_block in price_blocks:
            px0, py0, px1, py1, p_text, _, _ = p_block
            
            # --- A. ACHAR O NOME (Imediatamente ACIMA do preço) ---
            best_name = "Nome Desconhecido"
            min_dist_y = 9999
            
            # Centro horizontal do preço (para alinhar com o nome)
            p_center_x = (px0 + px1) / 2
            
            for b in text_blocks:
                bx0, by0, bx1, by1, b_text, _, _ = b
                
                # Ignora o próprio bloco de preço
                if b == p_block: continue
                
                # O bloco deve estar ACIMA do preço (by1 < py0)
                # E deve estar ALINHADO horizontalmente (overlap)
                if by1 <= py0 + 5: # +5 de tolerância
                    dist_y = py0 - by1
                    
                    # Verifica alinhamento horizontal (se estão na mesma coluna)
                    b_center_x = (bx0 + bx1) / 2
                    dist_x = abs(p_center_x - b_center_x)
                    
                    # Critérios:
                    # 1. Distância vertical pequena (máx 50px acima)
                    # 2. Alinhamento horizontal próximo (máx 20px de desvio)
                    if dist_y < 50 and dist_x < 40:
                        if dist_y < min_dist_y:
                            min_dist_y = dist_y
                            best_name = b_text.strip().replace('\n', ' ')

            # Limpeza do Nome (Remove "Estoque" ou lixo)
            if "Estoque" in best_name: best_name = "Nome Indisponível"
            if best_name.endswith(" R"): best_name = best_name[:-2] # Corrige bug visual

            # --- B. ACHAR A IMAGEM (Imediatamente ABAIXO do preço) ---
            best_image_bytes = None
            best_img_xref = f"no_img_{page_num}_{py0}"
            min_img_dist = 9999
            
            for xref, rect in page_images:
                # Imagem deve estar ABAIXO do preço (rect.y0 >= py1)
                # E alinhada horizontalmente
                if rect.y0 >= py1 - 10: # -10 tolerância
                    dist_y = rect.y0 - py1
                    
                    img_center_x = (rect.x0 + rect.x1) / 2
                    dist_x = abs(p_center_x - img_center_x)
                    
                    if dist_y < 100 and dist_x < 40: # Imagem logo abaixo
                        if dist_y < min_img_dist:
                            min_img_dist = dist_y
                            try:
                                extracted = doc.extract_image(xref)
                                best_image_bytes = extracted["image"]
                                best_img_xref = f"{page_num}_{xref}"
                            except:
                                pass

            # --- C. EXTRAIR VALORES ---
            # Extrai preço e peso do texto do bloco âncora
            price_match = re.search(r'R\$\s?([\d,.]+)', p_text)
            weight_match = re.search(r'\|\s?([\d,.]+)\s?g', p_text)
            
            price = price_match.group(1) if price_match else ""
            weight = weight_match.group(1) if weight_match else ""
            
            # ADICIONAR À LISTA
            # Usa o xref da imagem + index como ID único provisório
            if best_name and best_name != "Nome Desconhecido":
                products.append({
                    "id": best_img_xref, 
                    "image_bytes": best_image_bytes,
                    "code": best_name,
                    "price": price,
                    "weight": weight,
                    "raw_text": p_text
                })

    return products

# --- 2. GERADOR DE PDF ---
def generate_list_pdf(selected_items):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y_pos = height - 50
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y_pos, "Catálogo de Pedidos")
    y_pos -= 40
    row_height = 100 
    
    for item in selected_items:
        if y_pos < 100:
            c.showPage()
            y_pos = height - 50
        
        try:
            img_reader = ImageReader(io.BytesIO(item['image_bytes']))
            img_w, img_h = img_reader.getSize()
            aspect = img_h / float(img_w)
            display_h = 80
            display_w = display_h / aspect
            c.drawImage(img_reader, 40, y_pos - display_h, width=display_w, height=display_h)
        except:
            c.drawString(40, y_pos - 40, "[Erro Imagem]")

        text_x = 150 
        current_text_y = y_pos - 20
        c.setFont("Helvetica-Bold", 12)
        c.drawString(text_x, current_text_y, f"Ref: {item['code']}")
        
        c.setFont("Helvetica", 11)
        current_text_y -= 18
        if item['price']:
            c.drawString(text_x, current_text_y, f"Preço: {item['price']}")
        else:
             c.drawString(text_x, current_text_y, "Preço: Sob Consulta")

        current_text_y -= 15
        if item['weight']:
            c.drawString(text_x, current_text_y, f"Peso: {item['weight']}")
            
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.line(40, y_pos - 90, width - 40, y_pos - 90)
        y_pos -= row_height 

    c.save()
    buffer.seek(0)
    return buffer

# --- 3. CALLBACK PARA SELECIONAR TODOS ---
def toggle_all():
    # Pega o valor do checkbox mestre
    master_state = st.session_state.master_checkbox
    # Aplica esse valor em TODOS os produtos
    for item in st.session_state.products:
        st.session_state[item['id']] = master_state

# --- 4. INTERFACE ---
st.title("💎 Gerador de Catálogo")
uploaded_pdf = st.file_uploader("Selecione seu arquivo PDF", type="pdf")

if "products" not in st.session_state:
    st.session_state.products = []
if "pdf_buffer" not in st.session_state:
    st.session_state.pdf_buffer = None

if uploaded_pdf is not None:
    if st.button("Processar Arquivo Original"):
        with st.spinner("Lendo PDF..."):
            st.session_state.products = extract_products_from_pdf(uploaded_pdf)
            st.session_state.pdf_buffer = None
            
            # Inicializa o estado de seleção de cada produto como False
            for item in st.session_state.products:
                if item['id'] not in st.session_state:
                    st.session_state[item['id']] = False
        
        if not st.session_state.products:
            st.error("Nenhum produto encontrado.")
        else:
            st.success(f"{len(st.session_state.products)} produtos carregados!")

    # SE TIVER PRODUTOS
    if st.session_state.products:
        st.divider()
        st.markdown("### Selecione os Produtos")
        
        # --- CHECKBOX MESTRE (FORA DO FORMULÁRIO) ---
        # Ele precisa ficar fora para o callback funcionar instantaneamente
        st.checkbox(
            "Selecionar Todos / Nenhum", 
            key="master_checkbox", 
            on_change=toggle_all
        )
        
        # Início do Formulário
        with st.form("my_form"):
            cols = st.columns(4)
            selected_indices = []
            
            for index, item in enumerate(st.session_state.products):
                col = cols[index % 4]
                with col:
                    st.image(item["image_bytes"], use_container_width=True)
                    st.markdown(f"**{item['code']}**")
                    st.caption(f"💰 {item['price']} | ⚖️ {item['weight']}")
                    
                    
                    # Criamos uma chave única usando o índice (index)
                    unique_key = f"chk_{index}_{item['code']}"
                    
                    is_selected = st.checkbox("Selecionar", key=unique_key)
                    
                    if is_selected:
                        selected_indices.append(index)
            
            st.divider()
            submitted = st.form_submit_button("Gerar PDF com Itens Selecionados")
        
        # --- LÓGICA DE GERAÇÃO E DOWNLOAD ---
        if submitted:
            if not selected_indices:
                st.warning("⚠️ Você precisa marcar pelo menos um produto!")
            else:
                with st.spinner("Criando o PDF..."):
                    selected_items = [st.session_state.products[i] for i in selected_indices]
                    st.session_state.pdf_buffer = generate_list_pdf(selected_items)
                st.success("✅ PDF Criado com Sucesso!")

        if st.session_state.pdf_buffer is not None:
            st.markdown("---")
            col_left, col_center, col_right = st.columns([1, 2, 1])
            
            # Nome dinâmico do arquivo
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