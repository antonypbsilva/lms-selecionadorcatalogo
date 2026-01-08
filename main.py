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
    
    code_pattern = re.compile(r"(BX\s[0-9A-Z\s]+)") 
    price_pattern = re.compile(r"(R\$\s?[\d,]+)")       
    weight_pattern = re.compile(r"(\d+,\d+\s?g)")       

    for page_num, page in enumerate(doc):
        image_list = page.get_images(full=True)
        text_blocks = page.get_text("blocks")
        
        for img_index, img in enumerate(image_list):
            xref = img[0]
            rects = page.get_image_rects(xref)
            if not rects: continue
            img_rect = rects[0] 
            
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            
            # ZONA DE CAPTURA
            captured_texts = []
            for block in text_blocks:
                b_x0, b_y0, b_x1, b_y1, b_text, _, _ = block
                vertical_dist = b_y0 - img_rect.y1
                img_center = (img_rect.x0 + img_rect.x1) / 2
                text_center = (b_x0 + b_x1) / 2
                dist_centers = abs(img_center - text_center)
                
                if 0 < vertical_dist < 130 and dist_centers < 50:
                    captured_texts.append(b_text)

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

                code_match = code_pattern.search(full_description)
                if code_match:
                    product_data["code"] = code_match.group(1).strip()
                
                price_match = price_pattern.search(full_description)
                if price_match:
                    product_data["price"] = price_match.group(1).strip()
                    
                weight_match = weight_pattern.search(full_description)
                if weight_match:
                    product_data["weight"] = weight_match.group(1).strip()
                
                if product_data["code"]:
                    products.append(product_data)
                
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
                    
                    # O Checkbox agora lê e escreve diretamente no session_state pelo ID
                    # Se o ID já existir (criado pelo toggle_all), ele usa aquele valor
                    is_selected = st.checkbox("Selecionar", key=item['id'])
                    
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