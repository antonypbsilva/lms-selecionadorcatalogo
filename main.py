import streamlit as st
import fitz  # PyMuPDF
import re
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import io

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Gerador de Catálogo", layout="wide")

# --- 1. FUNÇÃO DE EXTRAÇÃO (UNIVERSAL: AX, BX, COL, PING...) ---
def extract_products_from_pdf(uploaded_file):
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    products = []
    
    # REGEX ATUALIZADO:
    # [A-Z]{2,4} -> Aceita siglas de 2 a 4 letras (ex: BX, AX, COL, CONJ)
    # \s\d+      -> Seguido de espaço e números
    code_pattern = re.compile(r"([A-Z]{2,4}\s\d+[A-Z0-9\s]*)") 
    
    price_pattern = re.compile(r"(R\$\s?[\d,]+)")       
    weight_pattern = re.compile(r"(\d+,\d+\s?g)")       

    for page_num, page in enumerate(doc):
        image_list = page.get_images(full=True)
        text_blocks = page.get_text("blocks")
        
        for img_index, img in enumerate(image_list):
            xref = img[0]
            
            # Pega coordenadas da imagem
            rects = page.get_image_rects(xref)
            if not rects: continue
            img_rect = rects[0] 
            
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            
            # --- ZONA DE CAPTURA (Busca texto abaixo da imagem) ---
            captured_texts = []
            for block in text_blocks:
                b_x0, b_y0, b_x1, b_y1, b_text, _, _ = block
                
                # Distância vertical (até 130px abaixo da imagem)
                vertical_dist = b_y0 - img_rect.y1
                
                # Alinhamento horizontal (Centro com Centro)
                img_center = (img_rect.x0 + img_rect.x1) / 2
                text_center = (b_x0 + b_x1) / 2
                dist_centers = abs(img_center - text_center)
                
                # Se estiver embaixo e alinhado
                if 0 < vertical_dist < 130 and dist_centers < 50:
                    captured_texts.append(b_text)

            # Junta todo o texto encontrado numa string só
            full_description = " ".join(captured_texts).replace("\n", " ")
            
            if full_description:
                product_data = {
                    "id": f"{page_num}_{img_index}", # ID único
                    "image_bytes": image_bytes,
                    "code": "",
                    "price": "",
                    "weight": "",
                    "raw_text": full_description
                }

                # Extrai Código
                code_match = code_pattern.search(full_description)
                if code_match:
                    product_data["code"] = code_match.group(1).strip()
                
                # Extrai Preço
                price_match = price_pattern.search(full_description)
                if price_match:
                    product_data["price"] = price_match.group(1).strip()
                    
                # Extrai Peso
                weight_match = weight_pattern.search(full_description)
                if weight_match:
                    product_data["weight"] = weight_match.group(1).strip()
                
                # SÓ ADICIONA SE TIVER CÓDIGO DETECTADO
                if product_data["code"]:
                    products.append(product_data)
                
    return products

# --- 2. FUNÇÃO GERADORA DE PDF (LAYOUT EM LISTA) ---
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
        # Nova página se acabar o espaço
        if y_pos < 100:
            c.showPage()
            y_pos = height - 50
        
        # 1. Desenhar Imagem (Esquerda)
        try:
            img_reader = ImageReader(io.BytesIO(item['image_bytes']))
            img_w, img_h = img_reader.getSize()
            aspect = img_h / float(img_w)
            
            display_h = 80
            display_w = display_h / aspect
            
            c.drawImage(img_reader, 40, y_pos - display_h, width=display_w, height=display_h)
        except:
            c.drawString(40, y_pos - 40, "[Imagem Indisponível]")

        # 2. Desenhar Texto (Direita)
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
            
        # Linha Divisória
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.line(40, y_pos - 90, width - 40, y_pos - 90)
        
        y_pos -= row_height 

    c.save()
    buffer.seek(0)
    return buffer

# --- 3. CALLBACK PARA "SELECIONAR TODOS" ---
def toggle_all():
    # Aplica o estado do checkbox mestre em todos os itens
    master_state = st.session_state.master_checkbox
    for item in st.session_state.products:
        st.session_state[item['id']] = master_state

# --- 4. INTERFACE DO USUÁRIO ---
st.title("💎 Gerador de Catálogo Inteligente")
uploaded_pdf = st.file_uploader("Selecione seu arquivo PDF (Argolas, Anéis, Colares...)", type="pdf")

# Inicializa variáveis de sessão
if "products" not in st.session_state:
    st.session_state.products = []
if "pdf_buffer" not in st.session_state:
    st.session_state.pdf_buffer = None

# PROCESSAMENTO DO ARQUIVO
if uploaded_pdf is not None:
    if st.button("Processar Arquivo"):
        with st.spinner("Lendo catálogo e identificando produtos..."):
            st.session_state.products = extract_products_from_pdf(uploaded_pdf)
            st.session_state.pdf_buffer = None # Limpa PDF antigo se houver
            
            # Garante que todos os itens tenham um estado inicial "False" (desmarcado)
            for item in st.session_state.products:
                if item['id'] not in st.session_state:
                    st.session_state[item['id']] = False
        
        if not st.session_state.products:
            st.error("Nenhum produto identificado. Verifique se o PDF contém códigos (BX, AX, COL, etc).")
        else:
            st.success(f"{len(st.session_state.products)} produtos carregados com sucesso!")

    # SE TIVER PRODUTOS CARREGADOS
    if st.session_state.products:
        st.divider()
        
        # Checkbox "Selecionar Todos" (Fora do form para ser instantâneo)
        col_master, _ = st.columns([1, 4])
        with col_master:
            st.checkbox(
                "Selecionar Todos", 
                key="master_checkbox", 
                on_change=toggle_all
            )
        
        st.write("### Selecione os itens desejados:")

        # FORMULÁRIO DE SELEÇÃO
        with st.form("my_form"):
            cols = st.columns(4) # Grid de 4 colunas
            selected_indices = []
            
            for index, item in enumerate(st.session_state.products):
                col = cols[index % 4]
                with col:
                    # Exibe Imagem
                    st.image(item["image_bytes"], use_container_width=True)
                    # Exibe Texto
                    st.markdown(f"**{item['code']}**")
                    st.caption(f"💰 {item['price']} | ⚖️ {item['weight']}")
                    
                    # Checkbox Individual (Conectado ao session_state)
                    is_selected = st.checkbox("Incluir", key=item['id'])
                    
                    if is_selected:
                        selected_indices.append(index)
            
            st.divider()
            submitted = st.form_submit_button("Gerar PDF com Itens Selecionados", type="primary")
        
        # --- PÓS-PROCESSAMENTO (RODAPÉ) ---
        
        # 1. Gera o PDF se o botão foi clicado
        if submitted:
            if not selected_indices:
                st.warning("⚠️ Você precisa marcar pelo menos um produto na lista acima!")
            else:
                with st.spinner("Diagramando seu novo catálogo..."):
                    selected_items = [st.session_state.products[i] for i in selected_indices]
                    st.session_state.pdf_buffer = generate_list_pdf(selected_items)
                st.success("✅ PDF Criado! Baixe abaixo.")

        # 2. Mostra o botão de Download (Se existir PDF pronto)
        if st.session_state.pdf_buffer is not None:
            st.markdown("---")
            col_left, col_center, col_right = st.columns([1, 2, 1])
            
            # Cria nome dinâmico (Ex: Aneis_Selecionadas.pdf)
            nome_original = uploaded_pdf.name.replace(".pdf", "")
            nome_final = f"{nome_original}_Selecionadas.pdf"
            
            with col_center:
                st.download_button(
                    label="📥 BAIXAR CATÁLOGO AGORA",
                    data=st.session_state.pdf_buffer,
                    file_name=nome_final,
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True 
                )
