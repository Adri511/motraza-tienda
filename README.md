# La tienda de Motraza

Una página y una ilustración, sin dependencias y sin compilar nada. Enseña los tres
productos y recoge quién los quiere.

- `index.html` — la página entera, con sus estilos y su formulario dentro.
- `relieve.png` — el mapa de la portada, **generado y no dibujado**: relieve sombreado
  desde el noroeste sobre un terreno de ruido fractal, y los tres trazados buscados con A*
  sobre ese terreno penalizando la pendiente. Por eso el puerto sube con herraduras: no se
  las ha puesto nadie, es que subir de frente costaba más.
- `relieve.py` — el generador. **No hace falta subirlo a GitHub Pages**, solo se usa si
  algún día se quiere otro terreno: `python relieve.py` y vuelve a salir el PNG (unos 7
  segundos). Con la misma semilla sale exactamente el mismo dibujo, para que la página no
  cambie sola entre despliegues.

  Al terminar imprime unas medidas, que son la forma de saber si ha salido bien sin
  mirarlo: el puerto debe rondar **sinuosidad 2 con unas cuarenta herraduras** y quedarse
  por debajo de la pendiente típica del terreno; la comarcal del valle, sinuosidad 1,1 y
  ninguna herradura. Si el puerto sale con sinuosidad 1 es que el castigo por pendiente no
  está mordiendo y el trazado ha salido recto.

**No vende.** No cobra, no acepta tarjetas y no crea ningún contrato. Es una lista de
espera, y está escrito así en la propia página para que nadie se confunda. El motivo
está en `motraza/docs/plan-sostenibilidad.md` §2: para cobrar un euro en España hay que
ser autónomo, y ese paso se da cuando la cuenta lo justifique.

## Por qué vive fuera del repositorio de la app

Dos razones, y ninguna es de comodidad:

- **Google Play prohíbe cobrar bienes físicos por su sistema de pago.** Un parche
  bordado tiene que venderse fuera de la app por norma, no por elección.
- Un precio cambia sin publicar una versión nueva ni pasar otra revisión.

## Publicarla

Igual que la política de privacidad, con un repositorio público propio:

1. En GitHub, **New repository**, público. Por ejemplo `motraza-tienda`.
2. Sube **`index.html` y `relieve.png`**, los dos en la raíz. Si falta el segundo, la
   portada y la ficha del producto principal salen sin imagen.
3. **Settings → Pages**, *Deploy from a branch*, rama `main`, carpeta `/ (root)`.
4. La dirección queda `https://<usuario>.github.io/motraza-tienda/`.

Y entonces **hay que cambiar una constante en la app**: `URL_TIENDA`, en
`motraza/src/features/tienda/model/tienda.ts`. Hasta que se cambie, los botones de la
app abren una dirección que no existe.

## Antes de enseñársela a nadie

En el pie hay **dos huecos en amarillo**, los mismos que la política de privacidad: el
correo de contacto y el responsable del tratamiento. La página **recoge correos**, así
que esos dos datos no son adorno, son la obligación que acompaña a recogerlos.

## Cómo llegan las reservas

La página escribe en la tabla `reservas_tienda` de Supabase con la clave pública, la
misma que ya lleva la app dentro. Las reglas de acceso están en
`motraza/supabase/migrations/20260824120000_reservas_de_la_tienda.sql` y se reducen a
dos:

- **Cualquiera puede insertar.** La tienda es una web abierta y pedir cuenta antes de
  saber si el producto interesa mataría la medición.
- **Nadie puede leer, salvo un administrador.** Es una lista de correos: sin esa regla
  sería una fuga de datos personales servida por la API. Comprobado — un lector anónimo
  recibe `[]`.

Lo que sujeta el contenido son restricciones de la propia tabla y no la política de
acceso, porque **una política decide quién escribe, no qué escribe**. Están probadas:
producto inventado, correo inválido, código en minúscula, parche sin club, carnet con
club y correo repetido se rechazan los seis.

### Los tres productos

| `producto` | Qué es | Campos suyos |
|---|---|---|
| `ruta-3d` | La rodada impresa en relieve | `ruta_id` (opcional), `variante` |
| `parche-club` | El parche bordado | `codigo_club` (obligatorio) |
| `carnet-fisico` | El carnet en PVC | — |

`ruta_id` es **opcional incluso para `ruta-3d`**: quien llega desde la app trae una ruta
elegida, quien llega a la web por su cuenta no, y obligarle a poner un identificador que
no conoce sería un callejón sin salida.

Y guardar ese id **no da acceso al recorrido**. El trazado sigue detrás de RLS; para
imprimirlo hará falta que su dueño lo autorice, que es una conversación que toca tener
cuando el producto exista.

Para verlas, en el SQL de Supabase:

```sql
select producto, count(*), max(creado_en) from reservas_tienda group by producto;
select * from reservas_tienda order by creado_en desc;
```

## Los enlaces desde la app

La app abre la página ya apuntando a un producto:

    ?p=ruta-3d&r=<uuid de la ruta>&de=app
    ?p=parche-club&c=ABC234&de=app
    ?p=carnet-fisico&de=app

Por la dirección viajan dos cosas y ninguna es el rider: **el código del club** y **el
identificador de una ruta**. El código ya es público —va impreso en el QR del carnet— y el
id de una ruta es opaco: conocerlo no abre nada, porque el trazado sigue detrás de RLS.

Lo que no viaja nunca es quién eres, **ni el nombre de la ruta**, que lo escribe el rider y
puede ser «casa - trabajo». Una URL acaba en el historial y en los registros de quien la
vea pasar. Si algún día hace falta pre-rellenar algo del rider, se hará con un vale de un
solo uso. Hay una prueba que falla si alguien añade un parámetro de más.

## Lo que falta el día que se venda de verdad

- Alta de autónomo y **condiciones de venta**, gastos de envío y derecho de
  desistimiento de 14 días.
- Una pasarela que **no sea la de la tienda de aplicaciones**, porque son bienes
  físicos. Stripe no cobra cuota mensual, solo comisión por venta.
- Direcciones de envío, que son un dato personal nuevo y vuelven a tocar la política de
  privacidad.
