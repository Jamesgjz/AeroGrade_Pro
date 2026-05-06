import streamlit as st
import zipfile
import io
import os
from groq import Groq

# 1. CONFIGURACIÓN DE POTENCIA (1GB y Layout)
st.set_page_config(page_title="AeroGrade Pro - UNIMINUTO", layout="wide")

# 2. CAMPOS TOTALMENTE LIMPIOS (Para que tú pegues cada vez)
if 'enunciado' not in st.session_state:
    st.session_state.enunciado = ""
if 'plantilla' not in st.session_state:
    st.session_state.plantilla = ""

st.title("🛡️ AeroGrade Pro: Calificación Masiva Universal")
st.info("Configurado para Proyectos NetBeans, Videos, PDFs y más (Máx 1GB)")

# 3. INTERFAZ DE ENTRADA (Lienzo en blanco)
col1, col2 = st.columns(2)
with col1:
    st.session_state.enunciado = st.text_area(
        "Pega aquí el Enunciado de Canvas:", 
        value=st.session_state.enunciado, 
        height=250, 
        placeholder="Instrucciones de la actividad...",
        key="area_enunciado"
    )
with col2:
    st.session_state.plantilla = st.text_area(
        "Pega aquí la Plantilla HTML:", 
        value=st.session_state.plantilla, 
        height=250, 
        placeholder="Código HTML con REEMPLAZO_P1, REEMPLAZO_P2...",
        key="area_html"
    )

# 4. FUNCIÓN PARA DESCOMPRIMIR PROYECTOS (NetBeans / Java / ZIP)
def procesar_archivo_comprimido(archivo_zip):
    texto_acumulado = ""
    with zipfile.ZipFile(archivo_zip, 'r') as z:
        for nombre in z.namelist():
            # Filtramos solo archivos de interés académico y código fuente
            if nombre.endswith(('.java', '.sql', '.txt', '.xml', '.py', '.r', '.dax', '.html')):
                with z.open(nombre) as f:
                    try:
                        texto_acumulado += f"\n\n--- ARCHIVO: {nombre} ---\n"
                        texto_acumulado += f.read().decode('utf-8', errors='ignore')
                    except:
                        continue
    return texto_acumulado

# 5. CARGADOR DE ARCHIVOS INDUSTRIAL (Hasta 1GB)
archivos = st.file_uploader(
    "Sube aquí los trabajos (ZIP, PDF, MP4, etc.):", 
    accept_multiple_files=True
)

# 6. LÓGICA DE CONEXIÓN A GROQ (IA Gratuita)
# El 'System Prompt' entrena a la IA con tus reglas de UNIMINUTO
if "GROQ_API_KEY" in st.secrets:
    client = Groq(api_key=st.secrets["GROQ_API_KEY"])
    if archivos and st.button("🚀 Iniciar Calificación"):
        st.write(f"Procesando {len(archivos)} entregas...")
        # Aquí se ejecutará el bucle de calificación que terminaremos de pulir
else:
    st.warning("🔑 Pendiente: Configurar la API Key en los Secrets de la nube.")
