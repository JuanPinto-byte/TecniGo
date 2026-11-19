"""
Sprint 6 (TDD): FN-15 suspender usuarios, FN-17 simular pago, FN-18 comisión y
FN-16 reportes.

Estas pruebas se escribieron ANTES que el código (fase roja) y luego se
implementó lo mínimo para ponerlas en verde.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.messages import get_messages
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Categoria, Comision, ConfiguracionComision, Notificacion, Pago, PerfilTecnico, Solicitud, Usuario,
)

CLAVE = "ClaveSegura123!"
_contador = iter(range(100000, 999999))


def dt(y, m, d, h=0, mi=0, s=0):
    return timezone.make_aware(datetime(y, m, d, h, mi, s))


def mensajes(respuesta):
    return " ".join(str(m) for m in get_messages(respuesta.wsgi_request))


class Base(TestCase):
    def usuario(self, rol, nombre, estado=Usuario.Estado.ACTIVO):
        n = next(_contador)
        return Usuario.objects.create_user(
            correo=f"u{n}@example.com", password=CLAVE, cedula=str(n), nombre_completo=nombre,
            telefono="3001234567", rol=rol, estado=estado, direccion="Calle 10 # 5-5")

    def crear_cliente(self, nombre="Cliente Uno"):
        return self.usuario(Usuario.Rol.CLIENTE, nombre)

    def crear_admin(self, nombre="Admin Uno"):
        return self.usuario(Usuario.Rol.ADMINISTRADOR, nombre)

    def crear_tecnico(self, nombre="Técnico Uno", estado=Usuario.Estado.ACTIVO, disponible=True):
        u = self.usuario(Usuario.Rol.TECNICO, nombre, estado)
        PerfilTecnico.objects.create(
            usuario=u, especialidad=Categoria.PLOMERIA, ciudad="Bogotá",
            documento_certificacion="certificaciones/x.pdf", disponible=disponible)
        return u

    def solicitud(self, cliente, tecnico=None, estado=Solicitud.Estado.FINALIZADA):
        return Solicitud.objects.create(
            cliente=cliente, tecnico=tecnico, categoria=Categoria.PLOMERIA, estado=estado,
            descripcion="Fuga de agua en la cocina", direccion="Calle 10 # 5-5")

    def pago_exitoso(self, solicitud, monto=100000, ref="SBX-TEST"):
        pago = Pago.objects.create(solicitud=solicitud, medio_pago=Pago.Medio.TARJETA, monto=monto)
        pago.marcar_exitoso(ref)
        return pago


# =====================================================================
# FN-15 — Suspender usuarios
# =====================================================================
class SuspenderUsuariosTests(Base):
    def setUp(self):
        self.admin = self.crear_admin()
        self.cliente = self.crear_cliente()
        self.tecnico = self.crear_tecnico()
        self.client.force_login(self.admin)

    def url(self, u):
        return reverse("admin_usuario_accion", args=[u.pk])

    def suspender(self, u, motivo="Incumple las políticas"):
        return self.client.post(self.url(u), {"accion": "suspender", "motivo": motivo})

    def test_suspende_un_cliente_con_motivo_y_fecha(self):
        r = self.suspender(self.cliente)
        self.assertEqual(r.status_code, 302)
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.estado, Usuario.Estado.SUSPENDIDO)
        self.assertEqual(self.cliente.motivo_suspension, "Incumple las políticas")
        self.assertIsNotNone(self.cliente.fecha_suspension)

    def test_motivo_obligatorio(self):
        for vacio in ("", "   ", "\n\t"):
            self.suspender(self.cliente, vacio)
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.estado, Usuario.Estado.ACTIVO)

    def test_motivo_sin_campo_se_rechaza(self):
        self.client.post(self.url(self.cliente), {"accion": "suspender"})
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.estado, Usuario.Estado.ACTIVO)

    def test_motivo_limite_300_si_301_no(self):
        self.suspender(self.cliente, "x" * 301)
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.estado, Usuario.Estado.ACTIVO)
        self.suspender(self.cliente, "x" * 300)
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.estado, Usuario.Estado.SUSPENDIDO)

    def test_suspender_tecnico_fuerza_disponibilidad_inactiva(self):
        self.assertTrue(self.tecnico.perfil_tecnico.disponible)
        self.suspender(self.tecnico)
        perfil = PerfilTecnico.objects.get(usuario=self.tecnico)
        self.assertFalse(perfil.disponible)

    def test_usuario_suspendido_no_inicia_sesion_y_ve_mensaje_claro(self):
        self.suspender(self.cliente)
        self.client.logout()
        r = self.client.post(reverse("login"), {"correo": self.cliente.correo, "clave": CLAVE})
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertIn("suspendida", mensajes(r))

    def test_sesion_abierta_se_cierra_en_la_siguiente_peticion(self):
        self.client.force_login(self.cliente)
        Usuario.objects.get(pk=self.cliente.pk).suspender("motivo")
        r = self.client.get(reverse("cliente_inicio"))
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_reactivar_devuelve_activo_y_limpia_motivo(self):
        self.suspender(self.cliente)
        r = self.client.post(self.url(self.cliente), {"accion": "reactivar"})
        self.assertEqual(r.status_code, 302)
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.estado, Usuario.Estado.ACTIVO)
        self.assertEqual(self.cliente.motivo_suspension, "")
        self.assertIsNone(self.cliente.fecha_suspension)

    def test_reactivar_tecnico_no_recupera_disponibilidad(self):
        self.suspender(self.tecnico)
        self.client.post(self.url(self.tecnico), {"accion": "reactivar"})
        self.tecnico.refresh_from_db()
        self.assertEqual(self.tecnico.estado, Usuario.Estado.ACTIVO)
        self.assertFalse(PerfilTecnico.objects.get(usuario=self.tecnico).disponible)

    def test_reactivar_a_quien_no_esta_suspendido_no_hace_nada(self):
        self.client.post(self.url(self.cliente), {"accion": "reactivar"})
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.estado, Usuario.Estado.ACTIVO)

    def test_no_se_suspende_dos_veces_ni_se_pisa_el_motivo_original(self):
        self.suspender(self.cliente, "Primer motivo")
        self.suspender(self.cliente, "Segundo motivo")
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.motivo_suspension, "Primer motivo")

    def test_el_admin_no_puede_suspenderse_a_si_mismo(self):
        self.suspender(self.admin)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.estado, Usuario.Estado.ACTIVO)

    def test_no_se_puede_suspender_a_otro_administrador(self):
        otro = self.crear_admin("Otro Admin")
        self.suspender(otro)
        otro.refresh_from_db()
        self.assertEqual(otro.estado, Usuario.Estado.ACTIVO)

    def test_tecnico_pendiente_o_rechazado_no_se_suspende(self):
        # Si se pudiera, al "reactivar" quedaría activo sin haber sido aprobado.
        for estado in (Usuario.Estado.PENDIENTE_APROBACION, Usuario.Estado.RECHAZADO):
            t = self.crear_tecnico(f"T {estado}", estado=estado)
            self.suspender(t)
            t.refresh_from_db()
            self.assertEqual(t.estado, estado)

    def test_accion_desconocida_se_rechaza(self):
        r = self.client.post(self.url(self.cliente), {"accion": "borrar"})
        self.assertIn(r.status_code, (302, 400, 405))
        self.assertTrue(Usuario.objects.filter(pk=self.cliente.pk).exists())

    def test_usuario_inexistente_da_404(self):
        r = self.client.post(reverse("admin_usuario_accion", args=[99999]),
                             {"accion": "suspender", "motivo": "x"})
        self.assertEqual(r.status_code, 404)

    def test_get_no_permitido(self):
        self.assertEqual(self.client.get(self.url(self.cliente)).status_code, 405)

    def test_solo_el_administrador_puede(self):
        victima = self.crear_cliente("Victima")
        for quien in (self.cliente, self.tecnico):
            self.client.force_login(quien)
            r = self.suspender(victima)
            self.assertEqual(r.status_code, 302)
        self.client.logout()
        self.assertEqual(self.suspender(victima).status_code, 302)
        victima.refresh_from_db()
        self.assertEqual(victima.estado, Usuario.Estado.ACTIVO)

    def test_notifica_al_usuario_suspendido(self):
        self.suspender(self.cliente, "Spam")
        n = Notificacion.objects.get(usuario=self.cliente, tipo=Notificacion.Tipo.USUARIO_SUSPENDIDO)
        self.assertIn("Spam", n.mensaje)

    # ---- listado ----
    def ids(self, r):
        return {u.pk for u in r.context["usuarios"]}

    def test_listado_muestra_clientes_y_tecnicos_pero_no_administradores(self):
        r = self.client.get(reverse("admin_usuarios"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.ids(r), {self.cliente.pk, self.tecnico.pk})

    def test_listado_filtra_por_rol_estado_y_busqueda(self):
        self.suspender(self.cliente)
        url = reverse("admin_usuarios")
        self.assertEqual(self.ids(self.client.get(url, {"rol": "tecnico"})), {self.tecnico.pk})
        self.assertEqual(self.ids(self.client.get(url, {"estado": "suspendido"})), {self.cliente.pk})
        self.assertEqual(self.ids(self.client.get(url, {"q": self.tecnico.cedula})), {self.tecnico.pk})
        self.assertEqual(self.ids(self.client.get(url, {"q": "NoExisteNadie"})), set())
        self.assertEqual(len(self.ids(self.client.get(url, {"rol": "zzz", "estado": "zzz"}))), 2)

    def test_listado_escapa_el_motivo(self):
        self.suspender(self.cliente, "<script>alert(1)</script>")
        r = self.client.get(reverse("admin_usuarios"))
        self.assertNotContains(r, "<script>alert(1)</script>")

    def test_listado_solo_para_admin(self):
        self.client.force_login(self.cliente)
        self.assertEqual(self.client.get(reverse("admin_usuarios")).status_code, 302)


# =====================================================================
# FN-17 — Simular pago
# =====================================================================
def datos_tarjeta(**extra):
    hoy = timezone.localdate()
    base = {"medio_pago": "tarjeta", "monto": "100000", "numero": "4242424242424242",
            "cvv": "123", "vencimiento": f"{hoy.month:02d}/{(hoy.year + 2) % 100:02d}"}
    base.update(extra)
    return base


class PagoTests(Base):
    def setUp(self):
        self.cliente = self.crear_cliente()
        self.tecnico = self.crear_tecnico()
        self.sol = self.solicitud(self.cliente, self.tecnico)
        self.url = reverse("pagar_solicitud", args=[self.sol.pk])
        self.client.force_login(self.cliente)

    def pagar(self, **extra):
        return self.client.post(self.url, datos_tarjeta(**extra))

    # ---- camino feliz ----
    def test_formulario_visible_para_el_dueno(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_pago_exitoso_registra_pago_comprobante_y_comision(self):
        r = self.pagar()
        self.assertRedirects(r, reverse("comprobante_pago", args=[self.sol.pk]),
                             fetch_redirect_response=False)
        pago = Pago.objects.get(solicitud=self.sol)
        self.assertEqual(pago.estado, Pago.Estado.EXITOSO)
        self.assertEqual(pago.monto, 100000)
        self.assertEqual(pago.medio_pago, "tarjeta")
        self.assertTrue(pago.referencia_pasarela)
        self.assertIsNotNone(pago.fecha_pago)
        self.assertTrue(Comision.objects.filter(pago=pago).exists())

    def test_pago_exitoso_notifica_a_cliente_y_tecnico(self):
        self.pagar()
        for u in (self.cliente, self.tecnico):
            self.assertTrue(Notificacion.objects.filter(
                usuario=u, tipo=Notificacion.Tipo.PAGO_EXITOSO, solicitud=self.sol).exists())

    def test_nunca_se_guardan_datos_sensibles(self):
        self.pagar()
        pago = Pago.objects.get()
        textos = " ".join(str(getattr(pago, f.name)) for f in Pago._meta.fields)
        textos += " ".join(n.mensaje for n in Notificacion.objects.all())
        self.assertNotIn("4242424242424242", textos)
        self.assertNotIn("4242", textos.replace("SBX", ""))
        self.assertNotIn("123 ", textos + " ")

    # ---- quién y cuándo se puede pagar ----
    def test_solicitud_ajena_da_404(self):
        self.client.force_login(self.crear_cliente("Otro"))
        self.assertEqual(self.pagar().status_code, 404)
        self.assertFalse(Pago.objects.exists())

    def test_solo_si_esta_finalizada(self):
        for estado in (Solicitud.Estado.PENDIENTE, Solicitud.Estado.EN_CURSO, Solicitud.Estado.CANCELADA):
            s = self.solicitud(self.cliente, self.tecnico, estado)
            self.client.post(reverse("pagar_solicitud", args=[s.pk]), datos_tarjeta())
            self.assertFalse(Pago.objects.filter(solicitud=s).exists(), estado)

    def test_no_se_paga_dos_veces(self):
        self.pagar()
        self.pagar(monto="5000")
        self.assertEqual(Pago.objects.count(), 1)
        self.assertEqual(Comision.objects.count(), 1)
        self.assertEqual(Pago.objects.get().monto, 100000)

    def test_el_tecnico_y_el_anonimo_no_pagan(self):
        self.client.force_login(self.tecnico)
        self.pagar()
        self.client.logout()
        self.pagar()
        self.assertFalse(Pago.objects.exists())

    # ---- fallos de la pasarela ----
    def test_tarjeta_rechazada_da_mensaje_especifico_y_permite_reintentar(self):
        r = self.pagar(numero="4000000000000002")
        self.assertIn("rechaz", mensajes(r).lower())
        pago = Pago.objects.get()
        self.assertEqual(pago.estado, Pago.Estado.FALLIDO)
        self.assertTrue(pago.motivo_fallo)
        self.assertFalse(Comision.objects.exists())
        self.assertTrue(Notificacion.objects.filter(
            usuario=self.cliente, tipo=Notificacion.Tipo.PAGO_FALLIDO).exists())
        # reintento con una tarjeta buena: el mismo Pago pasa a exitoso
        self.pagar()
        pago.refresh_from_db()
        self.assertEqual(pago.estado, Pago.Estado.EXITOSO)
        self.assertEqual(pago.motivo_fallo, "")
        self.assertEqual(Pago.objects.count(), 1)
        self.assertEqual(Comision.objects.count(), 1)

    def test_cada_motivo_de_fallo_tiene_su_propio_mensaje(self):
        rechazo = mensajes(self.pagar(numero="4000000000000002"))
        fondos = mensajes(self.pagar(numero="4000000000009995"))
        timeout = mensajes(self.pagar(numero="4000000000000119"))
        self.assertIn("fondos", fondos.lower())
        self.assertIn("tiempo", timeout.lower())
        self.assertEqual(len({rechazo, fondos, timeout}), 3)

    # ---- validaciones: monto ----
    def test_monto_limites(self):
        for malo in ("999", "0", "-5", "abc", "", "1500.5", "10000001"):
            self.pagar(monto=malo)
            self.assertFalse(Pago.objects.exists(), repr(malo))
        self.pagar(monto="10000000")
        self.assertEqual(Pago.objects.get().monto, 10000000)

    def test_monto_minimo_1000_es_valido(self):
        self.pagar(monto="1000")
        self.assertEqual(Pago.objects.get().monto, 1000)

    # ---- validaciones: tarjeta ----
    def test_numero_de_tarjeta_invalido(self):
        for malo in ("4242424242424241", "424242424242", "42424242424242424242", "abcd424242424242", ""):
            self.pagar(numero=malo)
            self.assertFalse(Pago.objects.exists(), repr(malo))

    def test_numero_con_espacios_o_guiones_es_valido(self):
        self.pagar(numero="4242 4242 4242 4242")
        self.assertEqual(Pago.objects.get().estado, Pago.Estado.EXITOSO)

    def test_cvv_invalido(self):
        for malo in ("12", "12345", "abc", "", "1 2"):
            self.pagar(cvv=malo)
            self.assertFalse(Pago.objects.exists(), repr(malo))

    def test_cvv_de_3_y_4_digitos_valido(self):
        self.pagar(cvv="1234")
        self.assertTrue(Pago.objects.exists())

    def test_vencimiento_invalido_o_vencido(self):
        hoy = timezone.localdate()
        mes_anterior = hoy.replace(day=1) - timedelta(days=1)
        vencida = f"{mes_anterior.month:02d}/{mes_anterior.year % 100:02d}"
        for malo in ("13/30", "00/30", "1/2030", "abc", "", vencida, "01/20"):
            self.pagar(vencimiento=malo)
            self.assertFalse(Pago.objects.exists(), repr(malo))

    def test_vencimiento_del_mes_actual_aun_es_valido(self):
        hoy = timezone.localdate()
        self.pagar(vencimiento=f"{hoy.month:02d}/{hoy.year % 100:02d}")
        self.assertTrue(Pago.objects.exists())

    # ---- otros medios ----
    def test_medio_de_pago_invalido(self):
        for malo in ("efectivo", "", "TARJETA"):
            self.pagar(medio_pago=malo)
            self.assertFalse(Pago.objects.exists(), repr(malo))

    def test_pse(self):
        self.client.post(self.url, {"medio_pago": "pse", "monto": "50000", "banco": "aprobado"})
        self.assertEqual(Pago.objects.get().estado, Pago.Estado.EXITOSO)

    def test_pse_rechazado_y_banco_invalido(self):
        self.client.post(self.url, {"medio_pago": "pse", "monto": "50000", "banco": "rechazado"})
        self.assertEqual(Pago.objects.get().estado, Pago.Estado.FALLIDO)
        Pago.objects.all().delete()
        self.client.post(self.url, {"medio_pago": "pse", "monto": "50000", "banco": "inventado"})
        self.assertFalse(Pago.objects.exists())

    def test_billetera_valida_y_celulares_invalidos(self):
        self.client.post(self.url, {"medio_pago": "billetera", "monto": "50000", "celular": "3001234567"})
        self.assertEqual(Pago.objects.get().estado, Pago.Estado.EXITOSO)
        Pago.objects.all().delete()
        for malo in ("2001234567", "300123456", "30012345678", "abc", ""):
            self.client.post(self.url, {"medio_pago": "billetera", "monto": "50000", "celular": malo})
            self.assertFalse(Pago.objects.exists(), repr(malo))

    def test_billetera_sin_fondos(self):
        self.client.post(self.url, {"medio_pago": "billetera", "monto": "50000", "celular": "3000000000"})
        self.assertEqual(Pago.objects.get().estado, Pago.Estado.FALLIDO)

    # ---- modelo ----
    def test_marcar_exitoso_dos_veces_falla_y_no_duplica_comision(self):
        pago = Pago.objects.create(solicitud=self.sol, medio_pago="tarjeta", monto=80000)
        pago.marcar_exitoso("REF-1")
        with self.assertRaises(ValueError):
            Pago.objects.get(pk=pago.pk).marcar_exitoso("REF-2")
        self.assertEqual(Comision.objects.count(), 1)
        self.assertEqual(Pago.objects.get().referencia_pasarela, "REF-1")

    # ---- comprobante ----
    def test_comprobante_muestra_transaccion_monto_fecha_y_medio(self):
        self.pagar()
        r = self.client.get(reverse("comprobante_pago", args=[self.sol.pk]))
        self.assertEqual(r.status_code, 200)
        pago = Pago.objects.get()
        self.assertContains(r, pago.referencia_pasarela)
        self.assertContains(r, "100.000")
        self.assertContains(r, "Tarjeta")

    def test_el_cliente_no_ve_el_desglose_de_comision(self):
        self.pagar()
        r = self.client.get(reverse("comprobante_pago", args=[self.sol.pk]))
        self.assertNotContains(r, "omisión")
        self.assertNotContains(r, "90.000")

    def test_comprobante_ajeno_o_sin_pago_da_404(self):
        self.assertEqual(self.client.get(reverse("comprobante_pago", args=[self.sol.pk])).status_code, 404)
        self.pagar()
        self.client.force_login(self.crear_cliente("Otro"))
        self.assertEqual(self.client.get(reverse("comprobante_pago", args=[self.sol.pk])).status_code, 404)

    def test_comprobante_de_pago_fallido_da_404(self):
        self.pagar(numero="4000000000000002")
        self.assertEqual(self.client.get(reverse("comprobante_pago", args=[self.sol.pk])).status_code, 404)

    # ---- integración con el historial (FN-6) ----
    def test_historial_ofrece_pagar_y_luego_comprobante(self):
        r = self.client.get(reverse("cliente_historial"))
        self.assertContains(r, self.url)
        self.pagar()
        r = self.client.get(reverse("cliente_historial"))
        self.assertNotContains(r, self.url)
        self.assertContains(r, reverse("comprobante_pago", args=[self.sol.pk]))


# =====================================================================
# FN-18 — Comisión de la plataforma
# =====================================================================
class ComisionTests(Base):
    def setUp(self):
        self.cliente = self.crear_cliente()
        self.tecnico = self.crear_tecnico()
        self.admin = self.crear_admin()

    def nuevo_pago(self, monto):
        return self.pago_exitoso(self.solicitud(self.cliente, self.tecnico), monto)

    def test_porcentaje_por_defecto_10(self):
        self.assertEqual(ConfiguracionComision.actual().porcentaje, 10)

    def test_calcula_comision_y_neto(self):
        c = Comision.objects.get(pago=self.nuevo_pago(100000))
        self.assertEqual((c.monto_comision, c.monto_neto_tecnico), (10000, 90000))
        self.assertEqual(c.porcentaje_aplicado, 10)

    def test_porcentaje_configurable(self):
        cfg = ConfiguracionComision.actual(); cfg.porcentaje = Decimal("15"); cfg.save()
        c = Comision.objects.get(pago=self.nuevo_pago(100000))
        self.assertEqual((c.monto_comision, c.monto_neto_tecnico, c.porcentaje_aplicado), (15000, 85000, 15))

    def test_cambiar_el_porcentaje_no_altera_comisiones_ya_calculadas(self):
        c = Comision.objects.get(pago=self.nuevo_pago(100000))
        cfg = ConfiguracionComision.actual(); cfg.porcentaje = Decimal("50"); cfg.save()
        c.refresh_from_db()
        self.assertEqual(c.monto_comision, 10000)

    def test_redondeo_medio_hacia_arriba(self):
        c = Comision.objects.get(pago=self.nuevo_pago(1005))  # 100,5 -> 101
        self.assertEqual((c.monto_comision, c.monto_neto_tecnico), (101, 904))

    def test_comision_mas_neto_siempre_suma_el_monto(self):
        cfg = ConfiguracionComision.actual()
        for pct in ("0", "0.01", "7.5", "10", "33.33", "99.99", "100"):
            cfg.porcentaje = Decimal(pct); cfg.save()
            for monto in (1000, 1001, 1005, 9999, 123457, 10000000):
                c = Comision.objects.get(pago=self.nuevo_pago(monto))
                self.assertEqual(c.monto_comision + c.monto_neto_tecnico, monto, (pct, monto))
                self.assertGreaterEqual(c.monto_neto_tecnico, 0)

    def test_porcentaje_cero_y_cien(self):
        cfg = ConfiguracionComision.actual()
        cfg.porcentaje = Decimal("0"); cfg.save()
        c = Comision.objects.get(pago=self.nuevo_pago(50000))
        self.assertEqual((c.monto_comision, c.monto_neto_tecnico), (0, 50000))
        cfg.porcentaje = Decimal("100"); cfg.save()
        c = Comision.objects.get(pago=self.nuevo_pago(50000))
        self.assertEqual((c.monto_comision, c.monto_neto_tecnico), (50000, 0))

    def test_pago_fallido_no_genera_comision(self):
        pago = Pago.objects.create(solicitud=self.solicitud(self.cliente, self.tecnico),
                                   medio_pago="tarjeta", monto=50000)
        pago.marcar_fallido("Rechazado")
        self.assertFalse(Comision.objects.exists())

    def test_una_sola_comision_por_pago(self):
        pago = self.nuevo_pago(50000)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Comision.calcular_para(pago)
        self.assertEqual(Comision.objects.count(), 1)

    # ---- pantalla de configuración ----
    def url(self):
        return reverse("admin_comision")

    def test_el_admin_cambia_el_porcentaje(self):
        self.client.force_login(self.admin)
        r = self.client.post(self.url(), {"porcentaje": "12.5"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(ConfiguracionComision.actual().porcentaje, Decimal("12.50"))

    def test_limites_del_porcentaje(self):
        self.client.force_login(self.admin)
        for bueno in ("0", "100", "0.01", "99.99"):
            self.client.post(self.url(), {"porcentaje": bueno})
            self.assertEqual(ConfiguracionComision.actual().porcentaje, Decimal(bueno), bueno)
        ConfiguracionComision.actual()
        antes = ConfiguracionComision.actual().porcentaje
        for malo in ("-0.01", "100.01", "abc", "", "10,5", "10.123", "1e2", "NaN", "Infinity"):
            self.client.post(self.url(), {"porcentaje": malo})
            self.assertEqual(ConfiguracionComision.actual().porcentaje, antes, repr(malo))

    def test_pantalla_muestra_el_porcentaje_actual(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.url()), "10")

    def test_solo_el_admin_configura(self):
        for quien in (self.cliente, self.tecnico):
            self.client.force_login(quien)
            self.client.post(self.url(), {"porcentaje": "99"})
        self.client.logout()
        self.client.post(self.url(), {"porcentaje": "99"})
        self.assertEqual(ConfiguracionComision.actual().porcentaje, 10)


# =====================================================================
# FN-16 — Reportes básicos
# =====================================================================
class ReportesTests(Base):
    def setUp(self):
        self.admin = self.crear_admin()
        self.cliente = self.crear_cliente()
        self.tecnico = self.crear_tecnico()
        self.url = reverse("admin_reportes")
        self.client.force_login(self.admin)
        hoy = timezone.localdate()
        self.mes = hoy.replace(day=1)

    def finalizada(self, cuando):
        s = self.solicitud(self.cliente, self.tecnico)
        Solicitud.objects.filter(pk=s.pk).update(fecha_finalizacion=cuando)
        return s

    def con_comision(self, monto, cuando):
        p = self.pago_exitoso(self.solicitud(self.cliente, self.tecnico), monto)
        Comision.objects.filter(pago=p).update(fecha_calculo=cuando)
        return p

    def get(self, **params):
        return self.client.get(self.url, params)

    # ---- acceso y solo lectura ----
    def test_solo_el_admin_entra(self):
        self.assertEqual(self.get().status_code, 200)
        for quien in (self.cliente, self.tecnico):
            self.client.force_login(quien)
            self.assertEqual(self.get().status_code, 302)
        self.client.logout()
        self.assertEqual(self.get().status_code, 302)

    def test_es_de_solo_lectura(self):
        self.finalizada(timezone.now())
        antes = (Solicitud.objects.count(), Usuario.objects.count(), Pago.objects.count())
        for metodo in (self.client.post, self.client.put, self.client.delete, self.client.patch):
            self.assertEqual(metodo(self.url, {"x": "1"}).status_code, 405)
        self.assertEqual(antes, (Solicitud.objects.count(), Usuario.objects.count(), Pago.objects.count()))

    # ---- métricas ----
    def test_sin_datos_todo_en_cero(self):
        r = self.get()
        self.assertEqual((r.context["servicios"], r.context["comisiones"]), (0, 0))
        self.assertEqual(r.context["tecnicos_activos"], 1)

    def test_por_defecto_es_el_mes_en_curso(self):
        self.finalizada(timezone.now())
        self.finalizada(dt(self.mes.year, self.mes.month, 1, 0, 0, 0))              # primer instante: entra
        self.finalizada(dt(self.mes.year, self.mes.month, 1) - timedelta(seconds=1))  # mes pasado: no
        r = self.get()
        self.assertEqual(r.context["desde"], self.mes)
        self.assertEqual(r.context["hasta"], timezone.localdate())
        self.assertEqual(r.context["servicios"], 2)

    def test_solo_cuentan_las_finalizadas(self):
        for estado in (Solicitud.Estado.PENDIENTE, Solicitud.Estado.EN_CURSO, Solicitud.Estado.CANCELADA):
            s = self.solicitud(self.cliente, self.tecnico, estado)
            Solicitud.objects.filter(pk=s.pk).update(fecha_finalizacion=timezone.now())
        self.assertEqual(self.get().context["servicios"], 0)

    def test_rango_es_inclusivo_en_ambos_extremos(self):
        self.finalizada(dt(2026, 3, 9, 23, 59, 59))   # un segundo antes: fuera
        self.finalizada(dt(2026, 3, 10, 0, 0, 0))     # primer instante: dentro
        self.finalizada(dt(2026, 3, 15, 23, 59, 59))  # último instante: dentro
        self.finalizada(dt(2026, 3, 16, 0, 0, 0))     # un instante después: fuera
        r = self.get(desde="2026-03-10", hasta="2026-03-15")
        self.assertEqual(r.context["servicios"], 2)

    def test_rango_de_un_solo_dia(self):
        self.finalizada(dt(2026, 3, 10, 12))
        self.assertEqual(self.get(desde="2026-03-10", hasta="2026-03-10").context["servicios"], 1)

    def test_tecnicos_activos_son_aprobados_y_no_suspendidos(self):
        self.crear_tecnico("Pendiente", estado=Usuario.Estado.PENDIENTE_APROBACION)
        self.crear_tecnico("Rechazado", estado=Usuario.Estado.RECHAZADO)
        self.crear_tecnico("Suspendido", estado=Usuario.Estado.SUSPENDIDO)
        self.crear_tecnico("Activo dos")
        self.assertEqual(self.get().context["tecnicos_activos"], 2)  # el del setUp + "Activo dos"

    def test_comisiones_suman_solo_las_del_periodo(self):
        self.con_comision(100000, dt(2026, 3, 12, 10))   # 10.000
        self.con_comision(50000, dt(2026, 3, 14, 10))    # 5.000
        self.con_comision(80000, dt(2026, 4, 2, 10))     # fuera del rango
        r = self.get(desde="2026-03-10", hasta="2026-03-15")
        self.assertEqual(r.context["comisiones"], 15000)

    def test_pagos_fallidos_no_suman(self):
        p = Pago.objects.create(solicitud=self.solicitud(self.cliente, self.tecnico),
                                medio_pago="tarjeta", monto=90000)
        p.marcar_fallido("Rechazado")
        self.assertEqual(self.get().context["comisiones"], 0)

    # ---- fechas inválidas ----
    def test_fechas_invalidas_no_rompen_y_usan_el_defecto(self):
        for malo in ("2026-13-45", "abc", "26/03/2026", "2026-02-30", "", "'; DROP TABLE x;--"):
            r = self.get(desde=malo, hasta=malo)
            self.assertEqual(r.status_code, 200, repr(malo))
            self.assertEqual(r.context["desde"], self.mes, repr(malo))

    def test_desde_mayor_que_hasta_avisa_y_usa_el_defecto(self):
        r = self.get(desde="2026-03-20", hasta="2026-03-10")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["desde"], self.mes)
        self.assertIn("anterior", mensajes(r).lower())

    def test_rango_muy_grande_funciona(self):
        self.finalizada(dt(2026, 3, 10, 12))
        r = self.get(desde="2000-01-01", hasta="2100-12-31")
        self.assertEqual(r.context["servicios"], 1)
