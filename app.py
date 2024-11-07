import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import re
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import io
import pytz

# Page config
st.set_page_config(
    page_title="Análisis de Equipamiento FHOS",
    page_icon="🔧",
    layout="wide"
)

def convert_excel_date(excel_date):
    """Convert Excel date serial number to datetime"""
    try:
        if isinstance(excel_date, (int, float)) or (isinstance(excel_date, str) and excel_date.isdigit()):
            return pd.Timestamp('1899-12-30') + pd.Timedelta(days=float(excel_date))
        return pd.NaT
    except:
        return pd.NaT

# Load data
@st.cache_data
def load_data():
    """Load and preprocess data with error handling"""
    try:
        # Load all dataframes
        handpiece_df = pd.read_csv('data_311024/handpieces.csv')
        drv_df = pd.read_csv('data_311024/datos_drv_it.csv')
        treatments_df = pd.read_csv('data_311024/treatments.csv')
        treatments_id_df = pd.read_csv('data_311024/treatments_id.csv')

        # Convert fecha_corte without debug information
        drv_df['fecha_corte'] = drv_df['fecha_corte'].apply(convert_excel_date)

        return handpiece_df, drv_df, treatments_df, treatments_id_df
    except Exception as e:
        st.error(f"Error loading data: {str(e)}")
        return None, None, None, None

def get_suggested_cutoff_date(drv_df, din):
    """Get suggested cutoff date from drv_df for specific DIN"""
    try:
        fecha_corte = drv_df[drv_df['din'] == din]['fecha_corte'].iloc[0]
        fecha_corte = pd.to_datetime(fecha_corte)

        # Set timezone to UTC if naive
        if fecha_corte.tz is None:
            fecha_corte = fecha_corte.tz_localize('UTC')

        min_date = pd.Timestamp('2023-01-01', tz='UTC')

        if pd.isna(fecha_corte) or fecha_corte < min_date:
            return min_date

        return fecha_corte
    except (IndexError, KeyError):
        return pd.Timestamp('2023-01-01', tz='UTC')

def process_data(handpiece_df, treatments_df, treatments_id_df, din, cutoff_date):
    """Process and filter handpiece and treatment data"""
    # Process handpiece data
    handpiece_df = handpiece_df.copy()
    treatments_df = treatments_df.copy()

    # Convert cutoff_date to UTC timezone if not already
    if cutoff_date.tz is None:
        cutoff_date = pd.to_datetime(cutoff_date).tz_localize('UTC')

    # Process handpiece data
    handpiece_df['pulse_count'] = (handpiece_df['pulse_count'] / 3).round(0).astype(int)

    # Drop unnecessary columns
    handpiece_df.drop(columns=['use_count', 'prod_date', 'pulse_energy', 'burst_energy', 'activation_energy', 'modulation_energy', 'rn'], inplace=True)

    handpiece_df.rename(columns={
        'pulse_count': 'disparos_pulso',
        'burst_count': 'disparos_rafaga',
        'activation_count': 'disparos_activacion',
        'modulation_count': 'disparos_modulacion'
    }, inplace=True)

    # Calculate vida_util_restante and disparos_totales_reales
    # handpiece_df['vida_util_restante'] = handpiece_df.apply(
    #     lambda row: 4000000 - (row['pulse_count'] * 20) - (row['burst_count'] * 1) - (row['activation_count'] + row['modulation_count'])
    #     if re.search(r'1\d$', str(row['handpiece_id'])) else
    #     2000000 - (row['pulse_count'] * 10) - (row['burst_count'] * 1) - ((row['activation_count'] + row['modulation_count']) * 0.5)
    #     if re.search(r'2\d$', str(row['handpiece_id'])) else 'Manguera_no_identificada',
    #     axis=1
    # )

    # handpiece_df['disparos_totales_reales'] = handpiece_df.apply(
    #     lambda row: (row['pulse_count'] * 20) + (row['burst_count'] * 1) + (row['activation_count'] + row['modulation_count'])
    #     if re.search(r'1\d$', str(row['handpiece_id'])) else
    #     (row['pulse_count'] * 10) + (row['burst_count'] * 1) + ((row['activation_count'] + row['modulation_count']) * 0.5)
    #     if re.search(r'2\d$', str(row['handpiece_id'])) else 'Manguera_no_identificada',
    #     axis=1
    # )

    # Process handpiece IDs
    handpiece_df['handpiece_id'] = handpiece_df['handpiece_id'].apply(
        lambda x: 'F.F.' if re.search(r'2\d$', str(x)) else 'M.F.' if re.search(r'1\d$', str(x)) else 'Manguera_no_identificada'
    )

    # Rename columns
    handpiece_df.rename(columns={
        # 'use_count': 'disparos_totales_brutos',
        'created_at': 'ultima_fecha_uso',
        'handpiece_id': 'tipo_manipulo',
        'serial_number': 'numero_serie'
    }, inplace=True)

    # Filter by DIN and date
    filtered_handpiece_df = handpiece_df[handpiece_df['din'] == din].copy()

    # Convert dates properly
    try:
        filtered_handpiece_df['ultima_fecha_uso'] = pd.to_datetime(filtered_handpiece_df['ultima_fecha_uso'])
        # Handle timezone conversion safely
        if filtered_handpiece_df['ultima_fecha_uso'].dt.tz is None:
            filtered_handpiece_df['ultima_fecha_uso'] = filtered_handpiece_df['ultima_fecha_uso'].dt.tz_localize('UTC')
    except Exception as e:
        st.error(f"Error converting dates: {str(e)}")
        return pd.DataFrame(), pd.DataFrame()

    # Filter by date
    filtered_handpiece_df = filtered_handpiece_df[
        filtered_handpiece_df['ultima_fecha_uso'] >= cutoff_date
        ].sort_values(by='ultima_fecha_uso', ascending=False).reset_index(drop=True)

    # Add status
    today = pd.Timestamp.now(tz='UTC')
    filtered_handpiece_df['estado'] = filtered_handpiece_df['ultima_fecha_uso'].apply(
        lambda x: 'ACTIVO' if (today - x).days < 30 else 'INACTIVO'
    )

    filtered_handpiece_df = filtered_handpiece_df[[
        'ultima_fecha_uso', 'estado', 'din', 'tipo_manipulo', 'numero_serie', 'disparos_pulso', 'disparos_rafaga', 'disparos_activacion', 'disparos_modulacion'
    ]]

# Process treatments data
    treatments_df = treatments_df.merge(treatments_id_df, how='left', left_on='code', right_on='Treatment_ID')
    treatments_df = treatments_df.assign(
        Tipo=treatments_df['Tipo'].fillna('FHOS'),
        Subprograma=treatments_df['Subprograma'].fillna('FHOS genérico'),
        PVP=treatments_df['PVP'].fillna(60),
        Secuencia=treatments_df['Secuencia'].fillna(1.0)
    )

    # Filter treatments
    filtered_treatments_df = treatments_df[treatments_df['din'] == din].copy()

    # Convert treatment dates properly
    try:
        filtered_treatments_df['reported_at'] = pd.to_datetime(filtered_treatments_df['reported_at'])
        if filtered_treatments_df['reported_at'].dt.tz is None:
            filtered_treatments_df['reported_at'] = filtered_treatments_df['reported_at'].dt.tz_localize('UTC')
    except Exception as e:
        st.error(f"Error converting treatment dates: {str(e)}")
        return filtered_handpiece_df, pd.DataFrame()

    filtered_treatments_df = filtered_treatments_df[
        filtered_treatments_df['reported_at'] >= cutoff_date
        ].reset_index(drop=True)

    return filtered_handpiece_df, filtered_treatments_df

def format_datetime_for_display(dt):
    """Format datetime for display, handling timezone conversion"""
    if pd.isna(dt):
        return ""
    if not isinstance(dt, pd.Timestamp):
        dt = pd.to_datetime(dt)
    if dt.tz is None:
        dt = dt.tz_localize('UTC')
    return dt.tz_convert('Europe/Madrid').strftime('%Y-%m-%d %H:%M')

def create_treatment_summary(filtered_treatments_df):
    """Create summary of treatments"""
    resumen_tratamientos = filtered_treatments_df[filtered_treatments_df['Secuencia'] == 1.0].groupby('Tipo').agg(
        Cantidad=('Tipo', 'count'),
        PVP=('PVP', 'sum'),
    ).sort_values(by='Cantidad', ascending=False).reset_index()

    total_cantidad = resumen_tratamientos['Cantidad'].sum()
    total_pvp = resumen_tratamientos['PVP'].sum()

    resumen_tratamientos['% de Tratamientos'] = (resumen_tratamientos['Cantidad'] / total_cantidad * 100).round(2)
    resumen_tratamientos['% de Ingresos'] = (resumen_tratamientos['PVP'] / total_pvp * 100).round(2)

    return resumen_tratamientos

def create_subprogram_summary(filtered_treatments_df):
    """Create summary of subprograms"""
    resumen_subprogramas = filtered_treatments_df[filtered_treatments_df['Secuencia'] == 1.0].groupby('Subprograma').agg(
        Cantidad=('Subprograma', 'count'),
        PVP=('PVP', 'sum'),
    ).sort_values(by='Cantidad', ascending=False).reset_index()

    total_cantidad = resumen_subprogramas['Cantidad'].sum()
    total_pvp = resumen_subprogramas['PVP'].sum()

    resumen_subprogramas['% de Tratamientos'] = (resumen_subprogramas['Cantidad'] / total_cantidad * 100).round(2)
    resumen_subprogramas['% de Ingresos'] = (resumen_subprogramas['PVP'] / total_pvp * 100).round(2)

    return resumen_subprogramas

def generate_pdf_summary(filtered_handpiece_df, treatment_summary, subprogram_summary, din, cutoff_date):
    """Generate PDF summary report"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    story = []

    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30
    )
    story.append(Paragraph("Análisis de Equipamiento FHOS", title_style))
    story.append(Paragraph(f"DIN: {din}", styles['Heading2']))
    story.append(Paragraph(f"Fecha de corte: {format_datetime_for_display(cutoff_date)}", styles['Heading2']))

    # Explanatory text
    story.append(Spacer(1, 12))
    story.append(Paragraph("""
        Este informe contiene datos de los equipos RAMASON FHOS desde el 1 de enero de 2023 
        hasta el 31 de octubre de 2024. Estos datos son más precisos conforme más actualizados 
        sean ya que dichos equipos han tenido diversas actualizaciones que han mejorado la 
        categorización, precisión y optimización de dichos datos.
    """, styles['Normal']))

    # Handpiece Analysis
    story.append(Spacer(1, 12))
    story.append(Paragraph("Análisis de Manípulos", styles['Heading2']))

    # Add handpiece explanatory text
    story.append(Paragraph("""
        A continuación aparecerán todos los manípulos que han sido conectados a tu equipo. 
        Si ves muchos manípulos conectados en un periodo corto de fechas esto se debe a que 
        un técnico de servicio técnico ha conectado diversos manípulos a el equipo para realizar 
        pruebas de conexión y potencia, comparando el rendimiento de tus manípulos a otros 
        similares para diagnosticar si el error es de manípulo o del equipo. Los primeros dos 
        manípulos que aparecen serán los de tu equipo en este caso.
    """, styles['Normal']))

    story.append(Spacer(1, 12))

    # Format handpiece data with all columns
    display_columns = [
        'ultima_fecha_uso', 'estado', 'tipo_manipulo', 'numero_serie',
        'disparos_pulso', 'disparos_rafaga', 'disparos_activacion', 'disparos_modulacion'
    ]

    handpiece_data = filtered_handpiece_df[display_columns].copy()
    handpiece_data['ultima_fecha_uso'] = handpiece_data['ultima_fecha_uso'].apply(format_datetime_for_display)

    # Convert to list for PDF table
    handpiece_data = [handpiece_data.columns.tolist()] + handpiece_data.values.tolist()

    # Create table style
    table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 7),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ])

    # Create handpiece table with adjusted column widths
    handpiece_table = Table(handpiece_data)
    handpiece_table.setStyle(table_style)
    story.append(handpiece_table)

    # Treatment summaries
    if not treatment_summary.empty:
        story.append(Spacer(1, 20))
        story.append(Paragraph("Resumen de Tratamientos", styles['Heading2']))

        treatment_data = [treatment_summary.columns.tolist()] + treatment_summary.values.tolist()
        treatment_table = Table(treatment_data)
        treatment_table.setStyle(table_style)
        story.append(treatment_table)

    if not subprogram_summary.empty:
        story.append(Spacer(1, 20))
        story.append(Paragraph("Resumen por Subprogramas", styles['Heading2']))

        subprogram_data = [subprogram_summary.columns.tolist()] + subprogram_summary.values.tolist()
        subprogram_table = Table(subprogram_data)
        subprogram_table.setStyle(table_style)
        story.append(subprogram_table)

    doc.build(story)
    buffer.seek(0)
    return buffer

def generate_detailed_pdf(filtered_treatments_df, din, cutoff_date):
    """Generate detailed PDF report of treatments"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20, leftMargin=20, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    story = []

    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30
    )
    story.append(Paragraph("Detalle de Tratamientos", title_style))
    story.append(Paragraph(f"DIN: {din}", styles['Heading2']))
    story.append(Paragraph(f"Fecha de corte: {format_datetime_for_display(cutoff_date)}", styles['Heading2']))

    # Add new explanatory text
    story.append(Spacer(1, 12))
    story.append(Paragraph("""
        Esta tabla resume los tratamientos realizados con el equipo. Estos datos son más precisos 
        conforme más actuales sean ya que dichos equipos han tenido diversas actualizaciones desde 
        el 1 de enero de 2023 que han mejorado la categorización, precisión y optimización de dichos 
        datos. Estos datos tendrán más y más información conforme se vaya actualizando el equipo. 
        Si en un tratamiento sales del mismo para, por ejemplo, cambiar el fototipo o algún otro 
        parámetro definido para el mismo, dicho tratamiento se volverá a iniciar y a día de hoy 
        contabilizará dos veces en la tabla de tratamientos realizados. Estos datos cubren el rango 
        de fechas desde la "Fecha de corte" hasta el 31/10/2024.
    """, styles['Normal']))

    story.append(Spacer(1, 12))

    # Prepare treatment data
    treatments_df_export = filtered_treatments_df[['reported_at', 'code', 'Tipo', 'Subprograma', 'duration']].copy()
    treatments_df_export['reported_at'] = treatments_df_export['reported_at'].apply(format_datetime_for_display)
    treatments_df_export['duration'] = (treatments_df_export['duration'] / 60000).round(2)  # Convert to minutes

    treatments_data = [treatments_df_export.columns.tolist()] + treatments_df_export.values.tolist()

    # Create table style
    table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ])

    treatments_table = Table(treatments_data, repeatRows=1)
    treatments_table.setStyle(table_style)
    story.append(treatments_table)

    doc.build(story)
    buffer.seek(0)
    return buffer

def main():
    # Load data
    handpiece_df, drv_df, treatments_df, treatments_id_df = load_data()

    if all(df is not None for df in [handpiece_df, drv_df, treatments_df, treatments_id_df]):
        # Sidebar
        st.sidebar.title("Configuración")

        # DIN input
        din = st.sidebar.text_input(
            "DIN del equipo",
            value="CM-A30-000000",
            help="Introduce el DIN del equipo a analizar"
        )

        # Get suggested cutoff date and ensure it's timezone aware
        suggested_date = get_suggested_cutoff_date(drv_df, din)
        if suggested_date.tz is None:
            suggested_date = suggested_date.tz_localize('UTC')

        st.sidebar.info(f"Fecha de corte sugerida: {format_datetime_for_display(suggested_date)}")

        # Ensure min_date is timezone aware
        min_date = pd.Timestamp('2023-01-01', tz='UTC')

        # Now both dates are timezone aware for comparison
        default_date = max(suggested_date, min_date)

        # Convert to date for the date_input widget
        default_date_naive = default_date.tz_localize(None).date()
        min_date_naive = min_date.tz_localize(None).date()

        cutoff_date = st.sidebar.date_input(
            "Fecha de corte",
            value=default_date_naive,
            min_value=min_date_naive,
            max_value=datetime.now().date(),
            help="Selecciona la fecha de corte para el análisis"
        )

        # Convert back to timezone-aware datetime for processing
        cutoff_date = pd.Timestamp(cutoff_date).tz_localize('UTC')

        # Add analyze button
        analyze_button = st.sidebar.button("Analizar", type="primary")

        st.sidebar.text("Desarrollado con 🖤 por Belvi.")
        st.sidebar.text("Copyright © 2024 Belvi Digital S.L.")

        # Main content - only show when analyze button is clicked
        if analyze_button:
            st.title("Análisis de equipamiento FHOS")
            st.write(f"DIN: {din}")
            st.write(f"Fecha de corte: {format_datetime_for_display(cutoff_date)}")

            st.markdown("""
            Este informe contiene datos de los equipos RAMASON FHOS (ej. RAMASON FHOS PROCYON) 
            desde el 1 de enero de 2023 hasta el 31 de octubre de 2024. Estos datos son más precisos 
            conforme más actualizados sean ya que dichos equipos han tenido diversas actualizaciones 
            desde el 1 de enero de 2023 que han mejorado la categorización, precisión y optimización 
            de dichos datos.
            """)

            # Process data
            filtered_handpiece_df, filtered_treatments_df = process_data(
                handpiece_df, treatments_df, treatments_id_df, din, cutoff_date
            )

            # Handpiece Analysis
            st.subheader("Análisis de manípulos")
            st.markdown("""
            A continuación aparecerán todos los manípulos que han sido conectados a tu equipo. 
            Si ves muchos manípulos conectados en un periodo corto de fechas esto se debe a que 
            un técnico de servicio técnico ha conectado diversos manípulos a el equipo para realizar 
            pruebas de conexión y potencia, comparando el rendimiento de tus manípulos a otros 
            similares para diagnosticar si el error es de manípulo o del equipo. Los primeros dos 
            manípulos que aparecen serán los de tu equipo en este caso.
            """)

            st.dataframe(filtered_handpiece_df)

            # Treatment Analysis
            if not filtered_treatments_df.empty:
                st.subheader("Análisis de tratamientos realizados")

                col1, col2 = st.columns(2)

                with col1:
                    treatment_summary = create_treatment_summary(filtered_treatments_df)
                    fig1 = px.pie(
                        treatment_summary,
                        values='Cantidad',
                        names='Tipo',
                        title='Distribución de Tratamientos'
                    )
                    st.plotly_chart(fig1, use_container_width=True)

                with col2:
                    fig2 = px.pie(
                        treatment_summary,
                        values='PVP',
                        names='Tipo',
                        title='Distribución de Ingresos'
                    )
                    st.plotly_chart(fig2, use_container_width=True)

                st.subheader("Detalles de Tratamientos")
                st.dataframe(treatment_summary)

                st.subheader("Resumen por Subprogramas")
                subprogram_summary = create_subprogram_summary(filtered_treatments_df)
                st.dataframe(subprogram_summary)

                # PDF Download buttons
                col1, col2 = st.columns(2)
                with col1:
                    pdf_buffer = generate_pdf_summary(
                        filtered_handpiece_df,
                        treatment_summary,
                        subprogram_summary,
                        din,
                        cutoff_date
                    )
                    st.download_button(
                        "Descargar Informe Resumen PDF",
                        pdf_buffer,
                        file_name=f"informe_resumen_{din}.pdf",
                        mime="application/pdf"
                    )

                with col2:
                    detailed_pdf = generate_detailed_pdf(
                        filtered_treatments_df,
                        din,
                        cutoff_date
                    )
                    st.download_button(
                        "Descargar Informe Tratamientos Detalle PDF",
                        detailed_pdf,
                        file_name=f"informe_detallado_{din}.pdf",
                        mime="application/pdf"
                    )
            else:
                st.warning("No se encontraron tratamientos para el período seleccionado")

if __name__ == "__main__":
    main()