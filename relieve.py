# -*- coding: utf-8 -*-
"""Genera `relieve.png`: la ilustración del producto de la rodada impresa.

Tres cosas hacen que parezca un mapa de verdad y no una mancha de colores:

  * SOMBREADO. El color por altura, solo, sale plano. Lo que da volumen es
    iluminar la pendiente: se calcula la normal del terreno en cada píxel y se
    ilumina desde el noroeste, que es de donde viene la luz en todos los mapas
    en relieve desde hace un siglo. No es tradición porque sí — con la luz desde
    el sureste el ojo invierte el relieve y los valles se leen como crestas.

  * CARRETERAS QUE SUBEN COMO SUBE UNA CARRETERA. No son curvas dibujadas: se
    buscan con A* sobre el terreno, y cada tramo cuesta más cuanto más empinado
    es. Donde la ladera pasa de lo que admite el firme, el camino barato deja de
    ser el de frente y pasa a ser cruzarla en diagonal; al agotarse el lado,
    cruzar al otro. Las herraduras salen solas, que es lo que hace que se lea
    como un puerto y no como una raya.

  * ANTIALIASING POR DISTANCIA. Cada píxel se pinta según lo cerca que queda del
    eje de la línea, así que los bordes salen suaves sin renderizar al doble.

Al final imprime unas medidas del trazado —sinuosidad, herraduras, pendiente—
porque son la única forma de saber si esto ha salido bien sin mirarlo: una
sinuosidad de 20 significa que el camino deambula y nunca llega.

Determinista: misma semilla, mismo dibujo.

    python relieve.py
"""
import math, random, struct, zlib, heapq

SEMILLA    = 20260825
N          = 240          # rejilla del terreno y del buscador de caminos
LADO       = 820          # píxeles del PNG. Se enseña a ~480 px como mucho, así
                          # que con 820 hay de sobra hasta en pantalla retina y
                          # el fichero baja un tercio.
POSTERIZA  = 3            # redondear el color a múltiplos de 3 no se ve y hace
                          # que el PNG comprima bastante mejor: el sombreado
                          # lleva ruido fino del terreno y ese ruido es justo lo
                          # que impide que se comprima.
LUZ_AZ     = math.radians(315)
LUZ_ALT    = math.radians(45)
EXAGERA    = 2.2
NIVEL_AGUA = 0.30


# ------------------------------------------------------------------- terreno
def ruido_valor(semilla, lado):
    r = random.Random(semilla)
    g = [[r.random() for _ in range(lado + 1)] for _ in range(lado + 1)]
    def en(x, y):
        # Sin recortar, x=1 cae en el último nodo y el vecino ya no existe.
        x = min(max(x, 0.0), 0.999999); y = min(max(y, 0.0), 0.999999)
        fx, fy = x * lado, y * lado
        ix, iy = int(fx), int(fy)
        tx, ty = fx - ix, fy - iy
        tx = tx * tx * (3 - 2 * tx); ty = ty * ty * (3 - 2 * ty)
        a = g[iy][ix] * (1 - tx) + g[iy][ix + 1] * tx
        b = g[iy + 1][ix] * (1 - tx) + g[iy + 1][ix + 1] * tx
        return a * (1 - ty) + b * ty
    return en


def campo(semilla):
    """Suma de octavas. Con una sola escala el terreno sale como huevos
    apilados; lo que lo hace roca es que cada escala meta detalle sobre la
    anterior."""
    octavas = [(3, 1.0), (6, 0.52), (12, 0.27), (24, 0.14), (48, 0.07), (96, 0.035)]
    fns = [(ruido_valor(semilla + i * 977, l), a) for i, (l, a) in enumerate(octavas)]
    total = sum(a for _, a in fns)

    z = [[0.0] * N for _ in range(N)]
    for j in range(N):
        y = j / (N - 1)
        for i in range(N):
            x = i / (N - 1)
            v = sum(f(x, y) * a for f, a in fns) / total
            # |ruido - 0.5| invertido da filos en vez de lomas redondas: es lo
            # que separa una sierra de unas dunas.
            v = (1.0 - abs(v - 0.5) * 2.0) ** 1.3
            # El valle del río, que es por donde irá la comarcal.
            eje = 0.62 + 0.19 * math.sin(x * 2.3 + 0.7) - 0.24 * x
            v -= 0.60 * math.exp(-((y - eje) ** 2) / (2 * 0.050 ** 2))
            b = min(x, 1 - x, y, 1 - y)
            v *= min(1.0, b / 0.07)
            z[j][i] = v

    lo = min(min(f) for f in z); hi = max(max(f) for f in z)
    return [[(v - lo) / (hi - lo) for v in f] for f in z]


def bilineal(campo_, lado, x, y):
    fx = min(max(x, 0.0), 0.999999) * (lado - 1)
    fy = min(max(y, 0.0), 0.999999) * (lado - 1)
    i, j = int(fx), int(fy)
    tx, ty = fx - i, fy - j
    a = campo_[j][i] * (1 - tx) + campo_[j][i + 1] * tx
    b = campo_[j + 1][i] * (1 - tx) + campo_[j + 1][i + 1] * tx
    return a * (1 - ty) + b * ty


# ---------------------------------------------------------------- carreteras
# Rumbos: todos los (dx,dy) hasta distancia 2 sin factor común. Dan dieciséis
# direcciones en vez de ocho, y con ocho las herraduras salen en escalera.
VECINOS = [(dx, dy) for dx in range(-2, 3) for dy in range(-2, 3)
           if (dx or dy) and math.gcd(abs(dx), abs(dy)) == 1]


def trazar(z, inicio, destino, pendiente_max, penal=8.0):
    """Camino más barato entre dos puntos, con la pendiente penalizada.

    A* y no una caminata ávida: una caminata que solo mira el paso siguiente se
    queda dando vueltas por la ladera y nunca llega. Aquí el destino está
    garantizado, y lo que decide la FORMA del camino es cuánto se castiga la
    pendiente."""
    ini = (int(inicio[0] * (N - 1)), int(inicio[1] * (N - 1)))
    fin = (int(destino[0] * (N - 1)), int(destino[1] * (N - 1)))

    def h(nodo):
        return math.hypot(nodo[0] - fin[0], nodo[1] - fin[1])

    abierto = [(h(ini), 0.0, ini)]
    coste = {ini: 0.0}
    padre = {}
    visto = set()

    while abierto:
        _, g, nodo = heapq.heappop(abierto)
        if nodo in visto:
            continue
        visto.add(nodo)
        if nodo == fin:
            break
        x0, y0 = nodo
        z0 = z[y0][x0]
        for dx, dy in VECINOS:
            x1, y1 = x0 + dx, y0 + dy
            if not (3 <= x1 < N - 3 and 3 <= y1 < N - 3):
                continue
            z1 = z[y1][x1]
            if z1 < NIVEL_AGUA:          # una carretera no cruza el embalse
                continue
            d = math.hypot(dx, dy)
            pend = abs(z1 - z0) / d
            # El exceso, EN PROPORCIÓN al umbral y no en valor absoluto. Restando
            # a secas salen números diminutos —centésimas— que al elevarse al
            # cuadrado se quedan en nada y el castigo no llega a doler: el camino
            # sale recto por muy vertical que sea la ladera. Con la razón
            # pend/umbral, pasarse al triple pesa nueve veces más, que es lo que
            # empuja al trazado a cruzar la pendiente en vez de subirla.
            extra = max(0.0, pend / pendiente_max - 1.0)
            g2 = g + d * (1.0 + penal * extra * extra)
            sig = (x1, y1)
            if g2 < coste.get(sig, 1e18):
                coste[sig] = g2
                padre[sig] = nodo
                heapq.heappush(abierto, (g2 + h(sig), g2, sig))

    camino, nodo = [], fin
    if fin not in padre and fin != ini:
        return [], []
    while nodo != ini:
        camino.append(nodo)
        nodo = padre[nodo]
    camino.append(ini)
    camino.reverse()
    bruto = [(x / (N - 1), y / (N - 1)) for x, y in camino]
    return suavizar(bruto), bruto


def suavizar(pts, vueltas=2, ventana=2):
    """Media móvil: quita el escalón de la rejilla sin borrar las herraduras,
    que son giros mucho más amplios que un escalón."""
    for _ in range(vueltas):
        out = []
        for i in range(len(pts)):
            t = pts[max(0, i - ventana):min(len(pts), i + ventana + 1)]
            out.append((sum(p[0] for p in t) / len(t), sum(p[1] for p in t) / len(t)))
        pts = out
    return pts


# ------------------------------------------------------------------- pintado
class Lienzo:
    def __init__(self, lado):
        self.w = lado
        self.px = bytearray(lado * lado * 3)

    def set(self, i, j, rgb, alfa=1.0):
        if not (0 <= i < self.w and 0 <= j < self.w):
            return
        k = (j * self.w + i) * 3
        if alfa >= 1.0:
            self.px[k] = int(rgb[0]); self.px[k+1] = int(rgb[1]); self.px[k+2] = int(rgb[2])
        else:
            for c in range(3):
                self.px[k+c] = int(self.px[k+c] * (1 - alfa) + rgb[c] * alfa)

    def linea(self, pts, grosor, rgb, alfa=1.0, guiones=None):
        radio = grosor / 2.0
        recorrido = 0.0
        for k in range(len(pts) - 1):
            x0, y0 = pts[k][0] * self.w, pts[k][1] * self.w
            x1, y1 = pts[k+1][0] * self.w, pts[k+1][1] * self.w
            largo = math.hypot(x1 - x0, y1 - y0)
            if largo == 0:
                continue
            recorrido += largo
            if guiones and int(recorrido // guiones) % 2 == 1:
                continue
            vx, vy = (x1 - x0) / largo, (y1 - y0) / largo
            for j in range(int(min(y0, y1) - radio - 1), int(max(y0, y1) + radio + 2)):
                for i in range(int(min(x0, x1) - radio - 1), int(max(x0, x1) + radio + 2)):
                    px, py = i + 0.5 - x0, j + 0.5 - y0
                    t = max(0.0, min(largo, px * vx + py * vy))
                    d = math.hypot(px - vx * t, py - vy * t)
                    cob = max(0.0, min(1.0, radio + 0.5 - d))
                    if cob > 0:
                        self.set(i, j, rgb, cob * alfa)

    def disco(self, centro, radio, relleno, borde):
        cx, cy = centro[0] * self.w, centro[1] * self.w
        for j in range(int(cy - radio - 2), int(cy + radio + 3)):
            for i in range(int(cx - radio - 2), int(cx + radio + 3)):
                d = math.hypot(i + 0.5 - cx, j + 0.5 - cy)
                if d <= radio + 1:
                    col = borde if d > radio - 3.2 else relleno
                    self.set(i, j, col, max(0.0, min(1.0, radio + 1 - d)))

    def png(self, ruta):
        filas = b''.join(b'\x00' + bytes(self.px[j*self.w*3:(j+1)*self.w*3]) for j in range(self.w))
        def trozo(t, d):
            return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t+d) & 0xffffffff)
        out = (b'\x89PNG\r\n\x1a\n'
               + trozo(b'IHDR', struct.pack('>IIBBBBB', self.w, self.w, 8, 2, 0, 0, 0))
               + trozo(b'IDAT', zlib.compress(filas, 9))
               + trozo(b'IEND', b''))
        open(ruta, 'wb').write(out)
        return len(out)


# Verdes apagados y tierras: el naranja del trazado tiene que ser lo único vivo.
RAMPA = [
    (0.00, (24, 46, 56)), (0.30, (34, 66, 76)),
    (0.31, (56, 74, 55)), (0.42, (72, 92, 60)),
    (0.54, (104, 113, 68)), (0.66, (138, 130, 82)),
    (0.78, (168, 148, 106)), (0.88, (192, 176, 145)),
    (0.95, (216, 210, 198)), (1.00, (238, 236, 232)),
]


def color_de(v):
    for k in range(len(RAMPA) - 1):
        a, ca = RAMPA[k]; b, cb = RAMPA[k+1]
        if v <= b:
            t = 0 if b == a else (v - a) / (b - a)
            return (ca[0] + (cb[0]-ca[0])*t, ca[1] + (cb[1]-ca[1])*t, ca[2] + (cb[2]-ca[2])*t)
    return RAMPA[-1][1]


def main():
    z = campo(SEMILLA)

    # El terreno a resolución de píxel, calculado UNA vez. Sombra y curvas de
    # nivel lo leen de aquí; interpolar por cada uno multiplicaba el trabajo.
    H = [[bilineal(z, N, i / (LADO - 1), j / (LADO - 1)) for i in range(LADO)]
         for j in range(LADO)]

    lienzo = Lienzo(LADO)
    esc = (LADO - 1) * EXAGERA

    for j in range(LADO):
        fila = H[j]
        arriba = H[max(0, j-1)]; abajo = H[min(LADO-1, j+1)]
        for i in range(LADO):
            h = fila[i]
            if h <= NIVEL_AGUA:
                c = color_de(h * (0.30 / NIVEL_AGUA))
                lienzo.set(i, j, (int(c[0]), int(c[1]), int(c[2])))
                continue
            dzdx = (fila[min(LADO-1, i+1)] - fila[max(0, i-1)]) / 2 * esc
            dzdy = (abajo[i] - arriba[i]) / 2 * esc
            pend = math.atan(math.hypot(dzdx, dzdy))
            orient = math.atan2(dzdy, -dzdx)
            s = (math.sin(LUZ_ALT) * math.cos(pend)
                 + math.cos(LUZ_ALT) * math.sin(pend) * math.cos(LUZ_AZ - orient))
            s = min(1.22, (0.36 + 0.64 * max(0.0, s)) ** 0.85)
            c = color_de(h)
            lienzo.set(i, j, (min(255, int(c[0]*s)), min(255, int(c[1]*s)), min(255, int(c[2]*s))))

    # Curvas de nivel: lo que acaba de decir "esto es un mapa".
    for paso in range(1, 12):
        nivel = NIVEL_AGUA + paso * (1.0 - NIVEL_AGUA) / 12
        for j in range(1, LADO):
            fila = H[j]; ant = H[j-1]
            for i in range(1, LADO):
                a = fila[i]
                if a < NIVEL_AGUA:
                    continue
                if (a - nivel) * (fila[i-1] - nivel) < 0 or (a - nivel) * (ant[i] - nivel) < 0:
                    lienzo.set(i, j, (46, 42, 36), 0.22)

    # Pendientes típicas del terreno, para calibrar. Un umbral en abstracto no
    # significa nada: depende de lo escarpado que haya salido este mapa.
    muestras = sorted(abs(z[j][i] - z[j][i-1]) for j in range(1, N) for i in range(1, N))
    tipica = muestras[len(muestras) // 2]

    # Comarcal por el fondo del valle, senda de montaña, y el puerto —que es la
    # rodada—. Cada uno aguanta una pendiente distinta, y de ahí que dibujen
    # formas distintas sobre el mismo terreno.
    # Los tres umbrales están calibrados, no elegidos a ojo: con 0.35 de la
    # pendiente típica y penal=8 el puerto sale con sinuosidad ~2 y una cuarentena
    # de herraduras, que es lo que mide un puerto de verdad. Con 0.8 el trazado
    # sale casi recto, que es lo que hace una comarcal por el fondo del valle.
    valle,  valle_b  = trazar(z, (0.05, 0.60), (0.95, 0.30), tipica * 0.85, penal=2.0)
    senda,  senda_b  = trazar(z, (0.32, 0.55), (0.14, 0.15), tipica * 4.0,  penal=2.0)
    puerto, puerto_b = trazar(z, (0.08, 0.66), (0.82, 0.84), tipica * 0.35, penal=8.0)

    lienzo.linea(valle, 7.0, (34, 32, 28), 0.50)
    lienzo.linea(valle, 3.6, (228, 224, 216), 0.92)
    lienzo.linea(senda, 2.6, (252, 248, 240), 0.70, guiones=8)

    lienzo.linea(puerto, 14.0, (22, 18, 14), 0.45)
    lienzo.linea(puerto, 9.0, (255, 102, 0), 1.0)
    lienzo.linea(puerto, 3.2, (255, 178, 112), 0.5)

    lienzo.disco(puerto[0], 11, (255, 255, 255), (22, 18, 14))
    lienzo.disco(puerto[-1], 11, (255, 102, 0), (22, 18, 14))

    tam = lienzo.png('relieve.png')

    # Se mide sobre el camino EN BRUTO. Sobre el suavizado no vale: la media
    # móvil junta puntos, el divisor de la pendiente se va a cero y salen
    # pendientes de 9 donde el umbral era 0.003.
    def informe(nombre, pts):
        if len(pts) < 3:
            print(f'  {nombre:7} VACIO'); return
        recto = math.hypot(pts[-1][0]-pts[0][0], pts[-1][1]-pts[0][1])
        largo = sum(math.hypot(pts[k+1][0]-pts[k][0], pts[k+1][1]-pts[k][1]) for k in range(len(pts)-1))
        rumbos = [math.atan2(pts[k+1][1]-pts[k][1], pts[k+1][0]-pts[k][0]) for k in range(len(pts)-1)]
        herr = sum(1 for k in range(1, len(rumbos))
                   if abs(math.atan2(math.sin(rumbos[k]-rumbos[k-1]), math.cos(rumbos[k]-rumbos[k-1]))) > math.radians(100))
        # En CELDAS, que es la unidad en la que se calculó el umbral. Dividir
        # por la distancia normalizada da un número (N-1) veces mayor y sale una
        # pendiente de 300 donde el umbral era 0.003.
        pend = max(abs(bilineal(z, N, *pts[k+1]) - bilineal(z, N, *pts[k]))
                   / (math.hypot(pts[k+1][0]-pts[k][0], pts[k+1][1]-pts[k][1]) * (N - 1))
                   for k in range(len(pts)-1))
        print(f'  {nombre:7} sinuosidad={largo/max(recto,1e-9):5.2f}  herraduras={herr:3}  '
              f'pendiente={pend/tipica:4.2f}x la tipica')

    print(f'relieve.png  {tam/1024:.0f} KB  {LADO}x{LADO}   pendiente tipica={tipica:.4f}')
    informe('valle', valle_b); informe('senda', senda_b); informe('puerto', puerto_b)


if __name__ == '__main__':
    main()
