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
    
    # Regex apenas para extrair valores limpos (não usado mais para encontrar o produto)
    price_validator = re.compile(r"R\$\s?[\d,]+")
    
    for page_num, page in enumerate(doc):
        # 1. Extração de Blocos de Texto e Imagens
        text_blocks = page.get_text("blocks") # (x0, y0, x1, y1, text, block_no, block_type)
        # Ordena blocos verticalmente (y0) para leitura sequencial
        text_blocks.sort(key=lambda b: (b[1], b[0]))
        
        images = page.get_images(full=True)
        page_images_data = []
        
        # Prepara lista de imagens com suas posições
        for img in images:
            xref = img[0]
            rects = page.get_image_rects(xref)
            if not rects: continue
            # Considera apenas a primeira aparição da imagem na página
            r = rects[0]
            # Filtra ícones muito pequenos
            if r.width < 50 or r.height < 50: continue
            page_images_data.append({'xref': xref, 'rect': r, 'y': r.y0})
            
        # Ordena imagens pela posição vertical
        page_images_data.sort(key=lambda x: x['y'])

        # 2. Varredura por "Âncoras" (Linhas de Preço/Peso)
        for i, block in enumerate(text_blocks):
            block_text = block[4]
            # Limpa quebras de linha extras para análise
            clean_text = block_text.replace('\n', ' ').strip()
            
            # A LÓGICA DE OURO: O produto é identificado pela linha de Preço + Peso
            # Deve conter "R$" E "g" (gramas)
            if "R$" in clean_text and "g" in clean_text:
                
                # --- A. EXTRAÇÃO DO NOME ---
                # O nome está, visualmente, ACIMA do preço.
                # Verificamos se está no mesmo bloco (linha anterior) ou no bloco anterior.
                
                lines = block_text.split('\n')
                price_line_index = -1
                
                # Acha em qual linha do bloco está o preço
                for idx, line in enumerate(lines):
                    if "R$" in line and "g" in line:
                        price_line_index = idx
                        break
                
                raw_name = ""
                
                # CASO 1: O nome está no mesmo bloco, na linha de cima
                if price_line_index > 0:
                    raw_name = lines[price_line_index - 1].strip()
                
                # CASO 2: O nome está no bloco anterior (o mais comum se houver espaçamento)
                elif i > 0:
                    # Pega o texto do bloco anterior
                    raw_name = text_blocks[i-1][4].replace('\n', ' ').strip()
                
                # --- CORREÇÃO DO BUG DO "R" E LIMPEZA ---
                # Remove "Estoque" se tiver pegado errado
                if "Estoque" in raw_name: 
                    raw_name = "Nome Desconhecido"
                
                # Remove o " R" no final (erro de leitura do PDF)
                if raw_name.endswith(" R"):
                    product_code = raw_name[:-2].strip()
                else:
                    product_code = raw_name.strip()

                # --- B. EXTRAÇÃO DE VALORES ---
                # Pega Preço e Peso da linha atual
                current_line = lines[price_line_index] if price_line_index != -1 else clean_text
                
                p_match = re.search(r'(R\$\s?[\d,]+)', current_line)
                w_match = re.search(r'([\d,]+\s?g)', current_line)
                
                price = p_match.group(1) if p_match else ""
                weight = w_match.group(1) if w_match else ""
                
                # --- C. VINCULAR A IMAGEM CORRETA ---
                # A imagem do produto está VISUALMENTE ABAIXO da linha de preço.
                # Procuramos a imagem mais próxima cujo topo (y0) seja maior que o preço (y1)
                
                price_block_y_bottom = block[3] # y1 do bloco de texto
                best_image = None
                min_dist = 9999
                
                for img_data in page_images_data:
                    # A imagem deve começar abaixo do preço
                    dist = img_data['rect'].y0 - price_block_y_bottom
                    
                    # Tolerância: Deve estar abaixo (dist > -10) e não muito longe (< 300px)
                    if -10 < dist < 300:
                        if dist < min_dist:
                            min_dist = dist
                            best_image = img_data
                
                image_bytes = None
                img_xref = f"no_img_{page_num}_{i}" # ID fallback
                
                if best_image:
                    try:
                        extracted = doc.extract_image(best_image['xref'])
                        image_bytes = extracted["image"]
                        img_xref = f"{page_num}_{best_image['xref']}"
                    except:
                        pass
                
                # Adiciona à lista final se tiver nome válido
                if product_code and len(product_code) > 2:
                    products.append({
                        "id": img_xref,
                        "image_bytes": image_bytes, # Pode ser None se não achar imagem
                        "code": product_code,
                        "price": price,
                        "weight": weight,
                        "raw_text": clean_text
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