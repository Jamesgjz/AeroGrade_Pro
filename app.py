import streamlit as st
import pandas as pd
import requests
import re
import json
import io
import zipfile
import PyPDF2
import docx
import openpyxl
from bs4 import BeautifulSoup
import streamlit.components.v1 as components
from groq import Groq

# 1. Configuración Inicial
st.set_page_config(page_title="AeroGrade Pro - UNIMINUTO", layout="wide")

if 'estudiantes_evaluados' not in st.session_state:
    st.session_state['estudiantes_evaluados'] = []

# 2. Funciones de Canvas
def enviar_nota_canvas(domain, token, course_id, assignment_id, student_id, nota, comentario_html):
    url = f"{domain.rstrip('/')}/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/{student_id}"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "submission[posted_grade]": nota,
        "comment[text_comment]": comentario_html
    }
    try:
        response = requests.put(url, headers=headers, data=payload)
        response.raise_for_status()
        return True
    except Exception as e:
        return False

# 3. Interfaz - Barra Lateral (Configuración Canvas)
st.sidebar.header("⚙️ Configuración Canvas y API")
canvas_token = st.sidebar.text_input("Canvas API Token", type="password")
canvas_domain = st.sidebar.text_input('🌐 Dominio de Canvas', value='https://uniminuto.instructure.com')
curso_id = st.sidebar.text_input('🏫 ID del Curso en Canvas', value='11731')
actividad_id = st.sidebar.text_input('📝 ID de la Actividad', value='208144')

# 4. Interfaz - Campos Limpios (Enunciado y Plantilla)
st.title("🛡️ AeroGrade Pro: Sincronización UNIMINUTO")
st.markdown("---")

col1, col2 = st.columns(2)
with col1:
    st.session_state.enunciado = st.text_area(
        "📝 Pega aquí el Enunciado de Canvas:", 
        value=st.session_state.get('enunciado', ''), 
        height=200
    )
with col2:
    st.session_state.plantilla = st.text_area(
        "🖥️ Pega aquí el código HTML de la plantilla (REEMPLAZO_P1...):", 
        value=st.session_state.get('plantilla', ''), 
        height=200
    )

# 5. Carga de Archivos y CSV
st.subheader("📤 Archivos de Calificación")
col_csv1, col_csv2, col_zip = st.columns(3)
with col_csv1:
    archivo_calificaciones = st.file_uploader("Sube el CSV de calificaciones", type=["csv"])
with col_csv2:
    archivo_rubricas = st.file_uploader("Sube el CSV de rúbricas", type=["csv"])
with col_zip:
    archivo_zip = st.file_uploader('📦 Sube el .zip de entregas (Máx 1GB)', type=['zip'])

if archivo_calificaciones and archivo_rubricas:
    df_calificaciones = pd.read_csv(archivo_calificaciones)
    df_rubricas = pd.read_csv(archivo_rubricas)
    
    columnas_actividad = [col for col in df_calificaciones.columns if any(k in col for k in ['MA Evaluación', 'MT Evaluación', 'MT Evidencia'])]
    
    if columnas_actividad:
        actividad_seleccionada = st.selectbox("Elige la actividad a calificar:", columnas_actividad)
        rubrica_seleccionada = st.selectbox('Selecciona la rúbrica correspondiente:', df_rubricas['Rubric Name'].unique())
        rubrica_texto = df_rubricas[df_rubricas['Rubric Name'] == rubrica_seleccionada].to_csv(index=False)
        
        # Filtrar Metadata de Canvas
        df_filtrado = df_calificaciones[df_calificaciones['Student'].astype(str).str.strip() != 'Points Possible'].copy()
        
        if st.button('✅ Iniciar Motor de Evaluación Llama 3'):
            if not canvas_token or not curso_id:
                st.error("⚠️ Faltan datos de Canvas en la barra lateral.")
                st.stop()
            if "GROQ_API_KEY" not in st.secrets:
                st.error("⚠️ Falta configurar GROQ_API_KEY en los Secrets de Streamlit.")
                st.stop()
                
            client = Groq(api_key=st.secrets["GROQ_API_KEY"])
            
            for i, row in df_filtrado.iterrows():
                nombre_estudiante = row.get('Student', 'Desconocido')
                student_id = str(int(float(row.get('ID', 0))))
                nota_actual = row[actividad_seleccionada]
                
                # Saltar los que ya tienen nota
                if pd.notna(nota_actual) and str(nota_actual).strip() not in ['', '-']:
                    st.info(f'⏭️ {nombre_estudiante} ya tiene nota. Omitiendo...')
                    continue
                    
                # Extraer texto del ZIP
                texto_extraido = ""
                if archivo_zip:
                    with zipfile.ZipFile(archivo_zip, 'r') as z:
                        archivos_estudiante = [f for f in z.namelist() if student_id in f]
                        for f_name in archivos_estudiante:
                            with z.open(f_name) as f:
                                if f_name.endswith(('.java', '.txt', '.sql', '.html', '.py', '.r')):
                                    texto_extraido += f.read().decode('utf-8', errors='ignore') + "\n"
                                elif f_name.endswith('.pdf'):
                                    reader = PyPDF2.PdfReader(io.BytesIO(f.read()))
                                    for p in reader.pages: texto_extraido += p.extract_text() + "\n"
                                # NOTA: Aquí actúan las demás librerías que pusimos en requirements.txt
                
                if texto_extraido:
                    with st.expander(f"Evaluando a: {nombre_estudiante}", expanded=True):
                        st.write("🧠 Analizando entrega...")
                        
                        prompt = f"""Actúa como un experto en desarrollo de software y redes. Eres un profesor virtual en UNIMINUTO.
Evalúa esta entrega basándote en el ENUNCIADO y la RÚBRICA.

ENUNCIADO: {st.session_state.enunciado}
RÚBRICA: {rubrica_texto}

REGLAS OBLIGATORIAS:
- NO uses emojis, ni viñetas, ni íconos.
- PROHIBICIÓN ABSOLUTA DE VOCABULARIO: BAJO NINGUNA CIRCUNSTANCIA uses las palabras "crucial" o "clave" en tu respuesta. Si las ibas a usar, cámbialas por "fundamental", "importante" o "esencial".
- Escribe en segunda persona ('tú').
- p1 (Logros): Un párrafo destacando lo bueno.
- p2 (Mejoras): Un párrafo con áreas de oportunidad. NUNCA sugieras un reenvío del trabajo.
- p3 (Material): Un párrafo con referencias bibliográficas reales (1 en español, 1 en inglés).

ENTREGA DEL ESTUDIANTE:
{texto_extraido[:8000]}

RESPONDE ÚNICAMENTE CON UN JSON VÁLIDO CON LAS CLAVES: "nota" (número), "p1", "p2", "p3" (textos)."""

                        try:
                            respuesta = client.chat.completions.create(
                                model="llama3-70b-8192",
                                messages=[{"role": "user", "content": prompt}],
                                response_format={"type": "json_object"},
                                temperature=0.2
                            )
                            
                            resultado = json.loads(respuesta.choices[0].message.content)
                            
                            html_final = st.session_state.plantilla.replace('REEMPLAZO_P1', resultado.get('p1', ''))
                            html_final = html_final.replace('REEMPLAZO_P2', resultado.get('p2', ''))
                            html_final = html_final.replace('REEMPLAZO_P3', resultado.get('p3', ''))
                            
                            st.metric("Nota Asignada", resultado.get('nota', 0))
                            
                            if enviar_nota_canvas(canvas_domain, canvas_token, curso_id, actividad_id, student_id, resultado.get('nota', 0), html_final):
                                st.success(f"✅ Nota enviada a Canvas para {nombre_estudiante}")
                            else:
                                st.error("❌ Error al enviar a Canvas.")
                                
                        except Exception as e:
                            st.error(f"Error con la IA: {e}")
