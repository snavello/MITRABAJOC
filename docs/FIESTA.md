# Fiesta de Fin de Año: guía para SDN

Entradas con pago por MercadoPago (plan en `PLAN_FIESTA.md`). Vive en
Herramientas de `/entornos`: existe en local y Pruebas, 404 en Demo. El
sindicato nunca maneja dinero: la plata va de MercadoPago a su cuenta.

## Probar todo sin MercadoPago (modo simulado)

Con `MP_MOCK=1` el pago se simula adentro de la app, sin salir a internet.

1. Variables: `MP_MOCK=1` y `MP_WEBHOOK_SECRET=cualquier-cosa` (solo para el webhook).
2. Arranque: `/entornos` → Herramientas → Fiesta → «Armar la fiesta» (evento + primer
   administrador), o `POST /api/entornos/herramientas/fiesta/arranque`.
3. El administrador entra en `/fiesta/sindicato` (la clave inicial se cambia en el primer
   ingreso), carga el padrón (CSV `legajo;dni;nombre;mail`) y revisa la configuración.
4. El afiliado entra en `/fiesta` con legajo + DNI, reserva y «paga» en la página simulada
   (Aprobar / Rechazar / Dejar pendiente). Después ve su entrada.
5. En la puerta, el personal escanea el QR desde `/fiesta/sindicato` → Puerta.

## Cobrar de verdad (MercadoPago, Checkout Pro)

1. Entrá a <https://www.mercadopago.com.ar/developers/panel> con la cuenta que va a
   **cobrar** (para la prueba, la de SDN; para producción, la del sindicato).
2. «Crear aplicación» → producto **Checkout Pro**. Nombre: «Entradas Fiesta SUPARA».
3. En «Credenciales de prueba» copiá el **Access Token** (empieza con `TEST-`).
   Es el valor de `MP_ACCESS_TOKEN`.
4. En «Webhooks» (o «Notificaciones») → modo de pruebas → URL:
   `https://mitrabajo-pruebas.onrender.com/api/fiesta/mp/webhook`, evento **Pagos**.
   Guardá y copiá la **clave secreta**: es `MP_WEBHOOK_SECRET`. Es una sola por aplicación
   (la misma para prueba y producción); se revela con el ojo en Webhooks → Configurar
   notificaciones, y «Restablecer» genera otra (hay que actualizar la variable). La
   **Public Key** no se usa.
5. En Render, servicio de Pruebas → Environment: cargá `MP_ACCESS_TOKEN` y
   `MP_WEBHOOK_SECRET`, y **sacá** `MP_MOCK` (si está, gana y se simula todo). Redeploy.
6. En `/fiesta/sindicato` → Configuración, el estado de MercadoPago tiene que decir
   «real». Si falta una variable, lo dice.

Sin `MP_ACCESS_TOKEN` ni `MP_MOCK`, reservar responde «el cobro no está configurado».
Un webhook sin firma válida (o sin `MP_WEBHOOK_SECRET`) se rechaza con 401.

### Tarjetas de prueba

Pagá en una **ventana de incógnito** (si no, MercadoPago mezcla tu sesión de vendedor
con la de comprador y rechaza el pago). Con un usuario comprador de prueba, o sin sesión.

| Tarjeta | Número | Vence | CVV |
|---|---|---|---|
| Visa | 4509 9535 6623 3704 | 11/30 | 123 |
| Mastercard | 5031 7557 3453 0604 | 11/30 | 123 |

Titular según el resultado que se quiera: `APRO` aprueba, `OTHE` rechaza por error
general, `CONT` queda pendiente. Documento: DNI `12345678`.

**El mail del pagador tiene que ser de prueba: `test@testuser.com`.** Si ponés un mail
que pertenece a una cuenta real de MercadoPago (el tuyo, por ejemplo), el checkout
rechaza el pago con «Una de las partes con la que intentás hacer el pago es de
prueba», aunque la tarjeta sea de prueba: el pagador quedó identificado como real y el
vendedor es de prueba (así falló la primera prueba en Pruebas el 2026-11-12; con el
mail de prueba el pago se aprobó y la reserva pasó a pagada en un segundo). Lo otro que
anda es iniciar sesión en el checkout con un **comprador de prueba** (Cuentas de prueba
de la aplicación, tipo Comprador, con saldo ficticio): paga con saldo o con tarjeta.

Si el checkout te muestra tus cuentas y tu saldo reales es porque el navegador tenía tu
sesión de MercadoPago abierta: es solo la pantalla, el vendedor sigue siendo el de
prueba y MercadoPago no deja mover plata real contra él. Se evita con el incógnito.

Al aprobar, MercadoPago avisa al webhook y la reserva pasa a pagada (la pantalla del
afiliado lo confirma sola, con un máximo de espera de 2 minutos).

## Reglas que conviene saber

- La reserva sin pagar vence a los `minutos_vencimiento` de la configuración y devuelve
  el cupo. Si el pago llega aprobado después, se toma igual y, si ya no había lugar, queda
  marcada «sobrecupo» para que el sindicato lo resuelva. Nunca se pierde un pago.
- El monto del pago tiene que coincidir con el de la reserva; si no, se registra y NO se
  marca pagada.
- Devoluciones: no se hacen desde la app; se devuelven desde el panel de MercadoPago.
- La entrada se habilita `horas_antes` del evento; el QR se renueva solo cada 10 minutos
  (una captura vieja no entra).
- Ingreso con documento: pide motivo y queda quién y cuándo.

## Para pasar a producción con la cuenta del sindicato

1. La cuenta del sindicato crea su propia aplicación (pasos 1 a 4) y activa las
   **credenciales de producción** (MercadoPago pide completar los datos de la cuenta).
2. Las variables de ese entorno pasan a usar el Access Token de producción (sin `TEST-`)
   y la clave secreta del webhook **de producción** (el panel tiene una para cada modo);
   la URL del webhook es la del entorno de producción.
3. Hacer una compra real de monto bajo con una tarjeta propia y verificar que llegue la
   plata a la cuenta del sindicato.
4. `MP_MOCK` no debe estar definido en producción.
5. Nada de esto toca el dinero de Colm3na: no hay comisión ni intermediación de fondos.
