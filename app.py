import os
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, desc
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import io

# LIBRERÍAS WORD/PDF
from docxtpl import DocxTemplate
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from pypdf import PdfReader, PdfWriter

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'clave_segura_unap_2025')

# --- CONFIGURACIÓN BD ---
db_uri = os.environ.get('DATABASE_URL')

#if not db_uri:
    # === CONEXIÓN DIRECTA A LA NUBE (RENDER) ===
    # Esta es la dirección "External Database URL" sacada de tu imagen:
   #db_uri = "postgresql://db_biblioteca_f9zy_user:aKYvfUON1Wql05SGi90GWsFwSuf4NBNS@dpg-d4o8kt2dbo4c73ad2pe0-a.oregon-postgres.render.com/db_biblioteca_f9zy"

if db_uri and db_uri.startswith("postgres://"):
    db_uri = db_uri.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- MODELOS ---
class Alumno(db.Model):
    __tablename__ = 'alumnos'
    id = db.Column(db.Integer, primary_key=True)
    voucher = db.Column(db.String(50), index=True)
    dni = db.Column(db.String(20), index=True)
    fecha_pago = db.Column(db.String(20)) 
    monto = db.Column(db.Float) 
    
    nombre = db.Column(db.String(150))
    facultad = db.Column(db.String(150))
    escuela = db.Column(db.String(150))
    grado = db.Column(db.String(50))
    
    fecha_registro = db.Column(db.DateTime, default=datetime.now)
    numero_anual = db.Column(db.Integer)
    anio_registro = db.Column(db.Integer)

class Deudor(db.Model):
    __tablename__ = 'deudores'
    id = db.Column(db.Integer, primary_key=True)
    identificador = db.Column(db.String(50), unique=True)
    motivo = db.Column(db.String(255))
    nombre = db.Column(db.String(150))
    tipo = db.Column(db.String(50))
    facultad = db.Column(db.String(150))
    escuela = db.Column(db.String(150))

class Administrador(db.Model):
    __tablename__ = 'administradores'
    id = db.Column(db.Integer, primary_key=True)
    usuario = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    p_pagos = db.Column(db.Boolean, default=False)
    p_deudores = db.Column(db.Boolean, default=False)
    p_reportes = db.Column(db.Boolean, default=False)
    p_config = db.Column(db.Boolean, default=False)
    p_usuarios = db.Column(db.Boolean, default=False)

class Facultad(db.Model):
    __tablename__ = 'facultades'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), unique=True, nullable=False)

class Escuela(db.Model):
    __tablename__ = 'escuelas'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), unique=True, nullable=False)

class Grado(db.Model):
    __tablename__ = 'grados'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), unique=True, nullable=False)

# --- RUTAS DE ACCESO ---
@app.route('/', methods=['GET', 'POST'])
def atencion():
    error = None
    alumno_encontrado = None
    if request.method == 'POST':
        voucher = request.form.get('voucher', '').strip()
        dni = request.form.get('dni', '').strip()
        fecha = request.form.get('fecha', '').strip()

        deudor = Deudor.query.filter((Deudor.identificador==dni) | (Deudor.identificador==voucher)).first()
        if deudor:
            error = f"🚫 ACCESO DENEGADO: {deudor.tipo} bloqueado por '{deudor.motivo}'."
        else:
            alumno = Alumno.query.filter_by(voucher=voucher, dni=dni, fecha_pago=fecha).first()
            if alumno:
                if alumno.monto and alumno.monto < 57.50:
                    error = "❌ Error: El monto pagado es insuficiente (Menor a S/ 57.50)."
                elif alumno.nombre:
                    alumno_encontrado = alumno
                else:
                    flash("✅ Pago validado. Complete sus datos.")
                    return redirect(url_for('completar_datos', id=alumno.id))
            else:
                error = "❌ Error: Datos incorrectos."
    return render_template('atencion.html', error=error, alumno=alumno_encontrado)

@app.route('/login', methods=['GET', 'POST'])
def login_admin():
    if request.method == 'POST':
        usuario = request.form['usuario']
        password_ingresado = request.form['password']
        
        admin = Administrador.query.filter_by(usuario=usuario).first()
        
        if admin and check_password_hash(admin.password, password_ingresado):
            session['admin_logged_in'] = True
            session['admin_user'] = admin.usuario
            session['p_pagos'] = admin.p_pagos
            session['p_deudores'] = admin.p_deudores
            session['p_reportes'] = admin.p_reportes
            session['p_config'] = admin.p_config
            session['p_usuarios'] = admin.p_usuarios
            return redirect(url_for('admin'))
        else:
            flash("❌ Usuario o contraseña incorrectos")
            
    return render_template('login_admin.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_admin'))

# --- DASHBOARD ADMIN ---
@app.route('/admin', methods=['GET'])
def admin():
    if not session.get('admin_logged_in'): return redirect(url_for('login_admin'))
    
    t_vouchers = Alumno.query.count()
    t_emitidas = Alumno.query.filter(Alumno.nombre != None).count()
    t_pendientes = t_vouchers - t_emitidas
    t_deudores = Deudor.query.count()

    q_facultades = db.session.query(Alumno.facultad, func.count(Alumno.id)).filter(Alumno.facultad != None).group_by(Alumno.facultad).all()
    l_facultades = [row[0] for row in q_facultades]
    d_facultades = [row[1] for row in q_facultades]

    q_escuelas = db.session.query(Alumno.escuela, func.count(Alumno.id)).filter(Alumno.escuela != None).group_by(Alumno.escuela).order_by(func.count(Alumno.id).desc()).limit(10).all()
    l_escuelas = [row[0] for row in q_escuelas]
    d_escuelas = [row[1] for row in q_escuelas]

    q_grados = db.session.query(Alumno.grado, func.count(Alumno.id)).filter(Alumno.grado != None).group_by(Alumno.grado).all()
    l_grados = [row[0] for row in q_grados]
    d_grados = [row[1] for row in q_grados]

    repetidos = db.session.query(Alumno.dni, Alumno.nombre, func.count(Alumno.id).label('total')).filter(Alumno.nombre != None).group_by(Alumno.dni, Alumno.nombre).having(func.count(Alumno.id) > 1).order_by(desc('total')).limit(10).all()

    return render_template('admin.html', usuario=session.get('admin_user'),
                           t_vouchers=t_vouchers, t_emitidas=t_emitidas, t_pendientes=t_pendientes, t_deudores=t_deudores,
                           l_facultades=l_facultades, d_facultades=d_facultades,
                           l_escuelas=l_escuelas, d_escuelas=d_escuelas,
                           l_grados=l_grados, d_grados=d_grados,
                           repetidos=repetidos)

# --- MÓDULO PAGOS ---
@app.route('/admin/pagos', methods=['GET', 'POST'])
def admin_pagos():
    if not session.get('admin_logged_in'): return redirect(url_for('login_admin'))
    if not session.get('p_pagos'): 
        flash("⛔ No tienes permiso para acceder a PAGOS.")
        return redirect(url_for('admin'))

    if request.method == 'POST':
        if 'voucher_manual' in request.form:
            v = request.form['voucher_manual'].strip()
            d = request.form['dni_manual'].strip()
            f = request.form['fecha_manual'].strip()
            m_str = request.form['monto_manual'].strip()
            try:
                m_float = float(m_str)
                if m_float < 57.50:
                    flash(f"⚠️ Error: Monto S/{m_float} insuficiente. Mínimo S/ 57.50")
                elif not Alumno.query.filter_by(voucher=v).first():
                    db.session.add(Alumno(voucher=v, dni=d, fecha_pago=f, monto=m_float))
                    db.session.commit()
                    flash(f"✅ Pago registrado: {v}")
                else: flash("⚠️ Voucher ya existe.")
            except: flash("❌ El monto debe ser numérico.")

        elif 'archivo' in request.files:
            file = request.files['archivo']
            if file.filename != '':
                try:
                    if file.filename.endswith('.csv') or file.filename.endswith('.txt'):
                        df = pd.read_csv(file, header=None, dtype=str)
                    else:
                        df = pd.read_excel(file, dtype=str)
                    count = 0
                    ignorados = 0
                    for _, row in df.iterrows():
                        if len(row) < 4: continue
                        v = str(row[0]).strip()
                        d = str(row[1]).strip()
                        f_pago = str(row[2]).strip()
                        m_raw = str(row[3]).strip()
                        try:
                            m_float = float(m_raw)
                            if m_float >= 57.50:
                                if not Alumno.query.filter_by(voucher=v).first():
                                    db.session.add(Alumno(voucher=v, dni=d, fecha_pago=f_pago, monto=m_float))
                                    count += 1
                            else: ignorados += 1
                        except: ignorados += 1
                    db.session.commit()
                    flash(f"✅ Carga Masiva: {count} nuevos.")
                except Exception as e: flash(f"Error: {e}")
        return redirect(url_for('admin_pagos'))
    pagos = Alumno.query.order_by(Alumno.id.desc()).limit(100).all()
    return render_template('admin_pagos.html', pagos=pagos)

@app.route('/admin/pagos/eliminar/<int:id>')
def admin_eliminar_pago(id):
    if not session.get('admin_logged_in') or not session.get('p_pagos'): return redirect(url_for('admin'))
    db.session.delete(Alumno.query.get_or_404(id))
    db.session.commit()
    flash("🗑️ Pago eliminado.")
    return redirect(url_for('admin_pagos'))

# --- RESTO DE MÓDULOS ---
@app.route('/admin/deudores', methods=['GET', 'POST'])
def admin_deudores():
    if not session.get('admin_logged_in'): return redirect(url_for('login_admin'))
    if not session.get('p_deudores'): 
        flash("⛔ Sin permiso.")
        return redirect(url_for('admin'))

    if request.method == 'POST':
        identificador = request.form['identificador'].strip()
        nombre = request.form['nombre'].strip().upper()
        tipo = request.form['tipo'].strip().upper()
        facultad = request.form['facultad'].strip().upper()
        escuela = request.form['escuela'].strip().upper()
        motivo = request.form['motivo'].strip()
        if not Deudor.query.filter_by(identificador=identificador).first():
            db.session.add(Deudor(identificador=identificador, nombre=nombre, tipo=tipo, facultad=facultad, escuela=escuela, motivo=motivo))
            db.session.commit()
            flash(f"🚫 Bloqueado: {nombre}")
        else: flash("⚠️ Ya en lista negra.")
        return redirect(url_for('admin_deudores'))
    return render_template('admin_deudores.html', deudores=Deudor.query.order_by(Deudor.id.desc()).all(), facultades=Facultad.query.all(), escuelas=Escuela.query.all())

@app.route('/admin/deudores/eliminar/<int:id>')
def admin_eliminar_deudor(id):
    if not session.get('admin_logged_in') or not session.get('p_deudores'): return redirect(url_for('admin'))
    db.session.delete(Deudor.query.get_or_404(id))
    db.session.commit()
    flash("✅ Desbloqueado.")
    return redirect(url_for('admin_deudores'))

@app.route('/admin/lista')
def admin_lista():
    if not session.get('admin_logged_in'): return redirect(url_for('login_admin'))
    if not session.get('p_reportes'): 
        flash("⛔ Sin permiso.")
        return redirect(url_for('admin'))
    alumnos = Alumno.query.filter(Alumno.nombre != None).order_by(Alumno.id.desc()).all()
    return render_template('admin_lista.html', alumnos=alumnos, usuario=session.get('admin_user'))

@app.route('/admin/usuarios', methods=['GET', 'POST'])
def admin_usuarios():
    if not session.get('admin_logged_in'): return redirect(url_for('login_admin'))
    if not session.get('p_usuarios'): 
        flash("⛔ Solo Super Admin.")
        return redirect(url_for('admin'))

    if request.method == 'POST':
        u = request.form['usuario'].strip()
        p = request.form['password'].strip()
        perm_pagos = 'p_pagos' in request.form
        perm_deudores = 'p_deudores' in request.form
        perm_reportes = 'p_reportes' in request.form
        perm_config = 'p_config' in request.form
        perm_usuarios = 'p_usuarios' in request.form

        if not Administrador.query.filter_by(usuario=u).first():
            clave_segura = generate_password_hash(p)
            nuevo = Administrador(usuario=u, password=clave_segura, 
                                  p_pagos=perm_pagos, p_deudores=perm_deudores, 
                                  p_reportes=perm_reportes, p_config=perm_config, 
                                  p_usuarios=perm_usuarios)
            db.session.add(nuevo)
            db.session.commit()
            flash(f"✅ Creado: {u}")
        else: flash("⚠️ Ya existe.")
        return redirect(url_for('admin_usuarios'))
    return render_template('admin_usuarios.html', admins=Administrador.query.all(), usuario_actual=session.get('admin_user'))

@app.route('/admin/usuarios/editar/<int:id>', methods=['GET', 'POST'])
def admin_editar_usuario(id):
    if not session.get('admin_logged_in') or not session.get('p_usuarios'): 
        return redirect(url_for('admin'))
    
    admin_edit = Administrador.query.get_or_404(id)
    
    if request.method == 'POST':
        admin_edit.usuario = request.form['usuario'].strip()
        
        # Solo actualizamos password si escribieron algo nuevo
        nueva_pass = request.form['password'].strip()
        if nueva_pass:
            admin_edit.password = generate_password_hash(nueva_pass)
            
        # Actualizar permisos
        admin_edit.p_pagos = 'p_pagos' in request.form
        admin_edit.p_deudores = 'p_deudores' in request.form
        admin_edit.p_reportes = 'p_reportes' in request.form
        admin_edit.p_config = 'p_config' in request.form
        admin_edit.p_usuarios = 'p_usuarios' in request.form
        
        try:
            db.session.commit()
            flash(f"✅ Usuario '{admin_edit.usuario}' actualizado.")
            return redirect(url_for('admin_usuarios'))
        except Exception as e:
            flash(f"❌ Error: {e}")
            
    return render_template('admin_usuarios_editar.html', admin=admin_edit)

@app.route('/admin/usuarios/eliminar/<int:id>')
def admin_eliminar_usuario(id):
    if not session.get('admin_logged_in') or not session.get('p_usuarios'): return redirect(url_for('admin'))
    adm = Administrador.query.get_or_404(id)
    if adm.usuario != session.get('admin_user'):
        db.session.delete(adm)
        db.session.commit()
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/facultades', methods=['GET', 'POST'])
def admin_facultades():
    if not session.get('admin_logged_in') or not session.get('p_config'): return redirect(url_for('admin'))
    if request.method == 'POST':
        n = request.form['nombre'].strip().upper()
        if not Facultad.query.filter_by(nombre=n).first():
            db.session.add(Facultad(nombre=n))
            db.session.commit()
    return render_template('admin_facultades.html', facultades=Facultad.query.order_by(Facultad.nombre).all())

@app.route('/admin/facultades/eliminar/<int:id>')
def admin_eliminar_facultad(id):
    if not session.get('admin_logged_in') or not session.get('p_config'): return redirect(url_for('admin'))
    db.session.delete(Facultad.query.get_or_404(id))
    db.session.commit()
    return redirect(url_for('admin_facultades'))

@app.route('/admin/escuelas', methods=['GET', 'POST'])
def admin_escuelas():
    if not session.get('admin_logged_in') or not session.get('p_config'): return redirect(url_for('admin'))
    if request.method == 'POST':
        n = request.form['nombre'].strip().upper()
        if not Escuela.query.filter_by(nombre=n).first():
            db.session.add(Escuela(nombre=n))
            db.session.commit()
    return render_template('admin_escuelas.html', escuelas=Escuela.query.order_by(Escuela.nombre).all())

@app.route('/admin/escuelas/eliminar/<int:id>')
def admin_eliminar_escuela(id):
    if not session.get('admin_logged_in') or not session.get('p_config'): return redirect(url_for('admin'))
    db.session.delete(Escuela.query.get_or_404(id))
    db.session.commit()
    return redirect(url_for('admin_escuelas'))

@app.route('/admin/grados', methods=['GET', 'POST'])
def admin_grados():
    if not session.get('admin_logged_in') or not session.get('p_config'): return redirect(url_for('admin'))
    if request.method == 'POST':
        n = request.form['nombre'].strip().upper()
        if not Grado.query.filter_by(nombre=n).first():
            db.session.add(Grado(nombre=n))
            db.session.commit()
    return render_template('admin_grados.html', grados=Grado.query.order_by(Grado.nombre).all())

@app.route('/admin/grados/eliminar/<int:id>')
def admin_eliminar_grado(id):
    if not session.get('admin_logged_in') or not session.get('p_config'): return redirect(url_for('admin'))
    db.session.delete(Grado.query.get_or_404(id))
    db.session.commit()
    return redirect(url_for('admin_grados'))

# --- GENERADORES (AQUÍ ESTÁ LA LÓGICA DE NOMBRE SEPARADO) ---
@app.route('/completar/<int:id>', methods=['GET', 'POST'])
def completar_datos(id):
    alumno = Alumno.query.get_or_404(id)
    if alumno.nombre and request.method == 'GET':
        flash("⚠️ Ya está registrado. Puede descargar su constancia directamente.")
        return render_template('atencion.html', alumno=alumno)

    if request.method == 'POST':
        # 1. Recibir datos separados
        paterno = request.form.get('paterno', '').strip().upper()
        materno = request.form.get('materno', '').strip().upper()
        nombres = request.form.get('nombres', '').strip().upper()
        
        # 2. Guardar con formato correcto: "PATERNO MATERNO, NOMBRES"
        alumno.nombre = f"{paterno} {materno}, {nombres}"
        
        alumno.facultad = request.form['facultad'].strip().upper()
        alumno.escuela = request.form['escuela'].strip().upper()
        alumno.grado = request.form['grado'].strip().upper()
        
        year_actual = datetime.now().year
        ultimo = Alumno.query.filter(Alumno.anio_registro == year_actual).order_by(Alumno.numero_anual.desc()).first()
        nuevo_numero = (ultimo.numero_anual + 1) if (ultimo and ultimo.numero_anual) else 1
        alumno.numero_anual = nuevo_numero
        alumno.anio_registro = year_actual
        
        db.session.commit()
        flash("✅ ¡Registro Completado!")
        return render_template('atencion.html', alumno=alumno)
    
    return render_template('completar_datos.html', alumno=alumno, 
                           facultades=Facultad.query.order_by(Facultad.nombre).all(), 
                           escuelas=Escuela.query.order_by(Escuela.nombre).all(),
                           grados=Grado.query.order_by(Grado.id).all())

@app.route('/ver_pdf/<int:id>')
def ver_pdf(id):
    return generar_pdf_sistema(id, download=False)

@app.route('/descargar_pdf/<int:id>')
def descargar_pdf(id):
    return generar_pdf_sistema(id, download=True)

def generar_pdf_sistema(id, download=False):
    alumno = Alumno.query.get_or_404(id)
    numero_final = alumno.numero_anual if alumno.numero_anual else alumno.id
    anio_final = alumno.anio_registro if alumno.anio_registro else datetime.now().year
    correlativo = f"{str(numero_final).zfill(3)}-{anio_final}-UB/DBU-UNAP"
    
    meses = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
    hoy = datetime.now()
    fecha_texto = f"{hoy.day} de {meses[hoy.month - 1]} de {hoy.year}"

    txt_facultad = alumno.facultad
    if txt_facultad.startswith("FACULTAD DE "): txt_facultad = txt_facultad.replace("FACULTAD DE ", "", 1)
    elif txt_facultad.startswith("FACULTAD "): txt_facultad = txt_facultad.replace("FACULTAD ", "", 1)

    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=A4)
    c.setFont("Times-Bold", 14) 
    texto_titulo = f"CONSTANCIA N° {correlativo}"
    x_titulo, y_titulo = 180, 700
    c.drawString(x_titulo, y_titulo, texto_titulo)
    ancho_texto = c.stringWidth(texto_titulo, "Times-Bold", 14)
    c.line(x_titulo, y_titulo - 3, x_titulo + ancho_texto, y_titulo - 3)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(180, 656, f"{alumno.nombre}")
    c.drawString(180, 615, f"{txt_facultad}")
    c.drawString(180, 575, f"{alumno.escuela}")
    c.setFont("Helvetica", 12)
    c.drawString(280, 430, f"San Juan Bautista, {fecha_texto}.")
    c.save()
    packet.seek(0)
    try:
        new_pdf = PdfReader(packet)
        existing_pdf = PdfReader(open("fondo_constancia.pdf", "rb"))
        output = PdfWriter()
        page = existing_pdf.pages[0]
        page.merge_page(new_pdf.pages[0])
        output.add_page(page)
        pdf_final = io.BytesIO()
        output.write(pdf_final)
        pdf_final.seek(0)
        return send_file(pdf_final, as_attachment=download, download_name=f"Constancia_{alumno.voucher}.pdf", mimetype='application/pdf')
    except: return "Falta fondo_constancia.pdf"

@app.route('/descargar_word/<int:id>')
def descargar_word(id):
    alumno = Alumno.query.get_or_404(id)
    numero_final = alumno.numero_anual if alumno.numero_anual else alumno.id
    anio_final = alumno.anio_registro if alumno.anio_registro else datetime.now().year
    
    txt_facultad = alumno.facultad
    if txt_facultad.startswith("FACULTAD DE "): txt_facultad = txt_facultad.replace("FACULTAD DE ", "", 1)
    elif txt_facultad.startswith("FACULTAD "): txt_facultad = txt_facultad.replace("FACULTAD ", "", 1)

    try:
        doc = DocxTemplate("plantilla_constancia.docx")
        meses = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
        hoy = datetime.now()
        context = {
            'correlativo': f"{str(numero_final).zfill(3)}-{anio_final}-UB/DBU-UNAP",
            'nombre': alumno.nombre,
            'facultad': txt_facultad,
            'escuela': alumno.escuela,
            'grado': alumno.grado,
            'fecha': f"{hoy.day} de {meses[hoy.month - 1]} de {hoy.year}"
        }
        doc.render(context)
        file_stream = io.BytesIO()
        doc.save(file_stream)
        file_stream.seek(0)
        return send_file(file_stream, as_attachment=True, download_name=f"Constancia_{alumno.voucher}.docx", mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    except: return "Falta plantilla_constancia.docx"

with app.app_context():
    db.create_all()
    # Crear usuario SUPER ADMIN (Encriptado)
    if not Administrador.query.filter_by(usuario='admin').first():
        clave_encriptada = generate_password_hash('admin123')
        db.session.add(Administrador(
            usuario='admin', 
            password=clave_encriptada, 
            p_pagos=True, p_deudores=True, p_reportes=True, p_config=True, p_usuarios=True
        ))
        db.session.commit()
    
    if Facultad.query.count() == 0:
        for f in ["FACULTAD DE CIENCIAS ECONÓMICAS Y DE NEGOCIOS", "FACULTAD DE INGENIERÍA DE SISTEMAS E INFORMÁTICA"]:
            db.session.add(Facultad(nombre=f))
        db.session.commit()

    if Escuela.query.count() == 0:
        for e in ["INGENIERÍA DE SISTEMAS", "DERECHO", "ENFERMERÍA", "CONTABILIDAD"]:
            db.session.add(Escuela(nombre=e))
        db.session.commit()

    if Grado.query.count() == 0:
        for g in ["BACHILLER", "TÍTULO PROFESIONAL", "MAESTRÍA", "DOCTORADO", "SEGUNDA ESPECIALIDAD"]:
            db.session.add(Grado(nombre=g))
        db.session.commit()
        print("✅ BD OK.")

if __name__ == '__main__':
    app.run(debug=True)