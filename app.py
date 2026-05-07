import streamlit as st
import pandas as pd
import requests
import re
import google.generativeai as genai
import json
import streamlit.components.v1 as components
import io
import PyPDF2
import docx
import openpyxl
import zipfile
import tempfile
import time
from groq import Groq

# 1. CONFIGURACIÓN E INTERFAZ
st.set_page_config(page_title="AeroGrade Pro - UNIMINUTO", layout="wide")

if 'estudiantes_evaluados' not in st.session_state:
    st.session_state['estudiantes_evaluados'] = []
if 'tokens_acumulados' not in st.session_state:
    st.session_state['tokens_acumulados'] = 0

# 2. FUNCIONES DE SOPORTE
def listar_modelos_gemini(api_key):
    try:
        genai.configure(api_key=api_key)
        return [m.name.replace('models/', '') for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    except: return ["gemini-1.5-flash", "gemini-2.0-flash-exp", "gemini-1.5-pro"]

def enviar_nota_canvas(domain, token, course_id, assignment_id, student_id, nota, comentario_html):
    url = f"{domain.rstrip('/')}/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/{student_id}"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"submission[posted_grade]": nota, "comment[text_comment]": comentario_html}
    try:
        response = requests.put(url, headers=headers, data=payload)
        return response.status_code == 200
    except: return False

# 3. SIDEBAR - CONFIGURACIÓN (DOMINIO RESTAURADO)
st.sidebar.header("⚙️ Configuración del Sistema")

# Campo de Dominio que me pediste
canvas_domain = st.sidebar.text_input('🌐 Dominio Canvas', value='https://uniminuto.instructure.com', help="Ej: https://miaulavirtual.uniminuto.edu")

motor_ia = st.sidebar.selectbox("Seleccione Cerebro:", ["Groq (Gratis - Llama 3.3)", "Google Gemini (Multimodal/Pago)"])

groq_key = st.secrets.get("GROQ_API_KEY", "")
gemini_key = st.sidebar.text_input("Gemini API Key:", type="password")
modelo_seleccionado = "gemini-1.5-flash"

if gemini_key and motor_ia == "Google Gemini (Multimodal/Pago)":
    opciones = listar_modelos_gemini(gemini_key)
    modelo_seleccionado = st.sidebar.selectbox("Versión de Gemini:", opciones)

canvas_token = st.sidebar.text_input("Canvas Token", type="password")
curso_id = st.sidebar.text_input('ID Curso', value='11731')
actividad_id = st.sidebar.text_input('ID Actividad', value='208144')

st.title("🚀 AeroGrade Pro: El Sistema Definitivo")
st.markdown("---")

# 4. PARÁMETROS DOCENTES
enunciado_global = st.text_area('📝 Enunciado de la Actividad:', height=100)
plantilla_global = st.text_area('🖥️ Plantilla HTML (REEMPLAZO_P1, P2, P3):', height=100)

st.subheader("📤 Carga de Archivos")
c1, c2, c3 = st.columns(3)
with c1: archivo_calificaciones = st.file_uploader("CSV Calificaciones", type=["csv"])
with c2: archivo_rubricas = st.file_uploader("CSV Rúbricas", type=["csv"])
with c3: archivo_zip = st.file_uploader('ZIP de Entregas', type=['zip'])

if archivo_calificaciones and archivo_rubricas:
    df_cal = pd.read_csv(archivo_calificaciones)
    df_rub = pd.read_csv(archivo_rubricas)
    columnas_act = [col for col in df_cal.columns if any(k in col for k in ['MA Evaluación', 'MT Evaluación', 'MT Evidencia'])]
    
    if columnas_act:
        actividad_sel = st.selectbox("🎯 ACTIVIDAD:", ["-- Seleccione --"] + columnas_act)
        
        if actividad_sel != "-- Seleccione --":
            rubrica_txt = df_rub[df_rub['Rubric Name'] == st.selectbox('Rúbrica:', df_rub['Rubric Name'].unique())].to_csv(index=False)
            df_final = df_cal[df_cal['Student'].astype(str).str.strip() != 'Points Possible'].copy()
            df_final = df_final[df_final['ID'].notna()]

            # MONITOR DE CONSUMO
            m1, m2, m3 = st.columns(3)
            m1.metric("Tokens Consumidos", f"{st.session_state['tokens_acumulados']:,}")
            if "Gemini" in motor_ia:
                costo_usd = (st.session_state['tokens_acumulados'] / 1_000_000) * 0.15
                m2.metric("Costo Est. (USD)", f"${costo_usd:.4f}")
            else:
                m2.metric("Costo Real", "$0.00 COP")
            m3.metric("Motor", motor_ia.split(" ")[0])

            # VISUALIZACIÓN DE RESULTADOS (Notas < 3.5 en rojo)
            if st.session_state['estudiantes_evaluados']:
                st.subheader("✅ Borradores para Validación")
                for e in st.session_state['estudiantes_evaluados']:
                    header_label = f"🧑‍🎓 {e['nombre']} - Nota: {e['nota']}"
                    with st.expander(header_label, expanded=False):
                        if e['nota'] < 3.5:
                            st.error(f"⚠️ Nota inferior a 3.5: Se recomienda revisión manual.")
                        components.html(e['html_final'], height=200, scrolling=True)

            st.divider()
            b_eval, b_reset = st.columns(2)
            with b_eval:
                btn_iniciar = st.button('🚀 INICIAR CALIFICACIÓN VISUAL', type="primary", use_container_width=True)
            with b_reset:
                if st.button("🧹 EMPEZAR DE CERO", use_container_width=True):
                    st.session_state['estudiantes_evaluados'] = []
                    st.session_state['tokens_acumulados'] = 0
                    st.rerun()

            if btn_iniciar:
                progreso = st.progress(0)
                status_box = st.empty()
                reloj_ia = st.empty()
                log_container = st.container()

                for idx, (i, row) in enumerate(df_final.iterrows()):
                    nombre = row.get('Student', 'Estudiante')
                    sid = str(int(float(row.get('ID', 0))))
                    partes_nombre = nombre.replace(',', '').lower().split()
                    
                    if sid in [e['student_id'] for e in st.session_state['estudiantes_evaluados']]:
                        progreso.progress((idx + 1) / len(df_final))
                        continue
                    
                    status_box.info(f"🔍 Evaluando a: **{nombre}**")
                    
                    contenidos_multimodal = []
                    if archivo_zip:
                        with zipfile.ZipFile(archivo_zip, 'r') as z:
                            archivos = [f for f in z.namelist() if sid in f or any(p in f.lower() for p in partes_nombre if len(p) > 3)]
                            for f_n in archivos:
                                with z.open(f_n) as f:
                                    datos = f.read()
                                    ext = f_n.lower()
                                    if "Gemini" in motor_ia and any(ext.endswith(e) for e in ['.pdf', '.png', '.jpg', '.jpeg']):
                                        with tempfile.NamedTemporaryFile(delete=False, suffix=ext[ext.rfind('.'):]) as tmp:
                                            tmp.write(datos); tmp_path = tmp.name
                                        archivo_ia = genai.upload_file(path=tmp_path)
                                        contenidos_multimodal.append(archivo_ia)
                                    else:
                                        contenidos_multimodal.append(f"\nArchivo: {f_n}\n{datos.decode('utf-8', errors='ignore')[:10000]}")

                    if contenidos_multimodal:
                        prompt = f"""Actúa como profesor de UNIMINUTO. Evalúa según ENUNCIADO: {enunciado_global} y RÚBRICA: {rubrica_txt}.
                        REGLAS:
                        1. Segunda persona (sujeto tácito). PROHIBIDO usar 'tú', 'usted', 'clave' o 'crucial'.
                        2. p1: Logros. p2: Mejoras (prohibido pedir reenvíos). p3: Material (Español e Inglés).
                        3. JSON: {{"nota": float, "p1": "string", "p2": "string", "p3": "string"}}"""

                        evaluado = False
                        while not evaluado:
                            try:
                                if "Groq" in motor_ia:
                                    client = Groq(api_key=groq_key)
                                    res_ia = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt + str(contenidos_multimodal)}], response_format={"type": "json_object"})
                                    res = json.loads(res_ia.choices[0].message.content)
                                    st.session_state['tokens_acumulados'] += res_ia.usage.total_tokens
                                else:
                                    genai.configure(api_key=gemini_key)
                                    model = genai.GenerativeModel(modelo_seleccionado)
                                    res_ia = model.generate_content([prompt] + contenidos_multimodal, generation_config={"response_mime_type": "application/json"})
                                    res = json.loads(res_ia.text)
                                    st.session_state['tokens_acumulados'] += model.count_tokens([prompt] + contenidos_multimodal).total_tokens

                                html = plantilla_global.replace('REEMPLAZO_P1', res['p1']).replace('REEMPLAZO_P2', res['p2']).replace('REEMPLAZO_P3', res['p3'])
                                
                                with log_container:
                                    if res['nota'] < 3.5: st.error(f"⚠️ {nombre} - Nota: {res['nota']}")
                                    else: st.success(f"✅ {nombre} - Nota: {res['nota']}")
                                
                                st.session_state['estudiantes_evaluados'].append({'nombre': nombre, 'student_id': sid, 'nota': float(res['nota']), 'html_final': html})
                                evaluado = True
                                
                            except Exception as e:
                                if "429" in str(e):
                                    for t in range(660, 0, -1):
                                        reloj_ia.error(f"🛑 Límite alcanzado. Retomando en {t//60:02d}:{t%60:02d}"); time.sleep(1)
                                    reloj_ia.empty()
                                else: st.error(f"Error con {nombre}: {e}"); evaluado = True
                    progreso.progress((idx + 1) / len(df_final))
                status_box.success("🎉 Ciclo terminado.")

# 6. SINCRONIZACIÓN CON CANVAS
if st.session_state['estudiantes_evaluados']:
    st.divider()
    if st.button("📤 SINCRONIZAR TODO CON CANVAS AHORA", type="primary", use_container_width=True):
        total_s = len(st.session_state['estudiantes_evaluados'])
        for idx, est in enumerate(st.session_state['estudiantes_evaluados']):
            st.toast(f"🚀 Subiendo ({idx+1}/{total_s}): {est['nombre']}")
            # Usa el dominio capturado en la sidebar
            enviar_nota_canvas(canvas_domain, canvas_token, curso_id, actividad_id, est['student_id'], est['nota'], est['html_final'])
        st.balloons(); st.success("Sincronización exitosa!"); time.sleep(2); st.rerun()
