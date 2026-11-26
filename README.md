# bot-apuestas

Análisis de datos sobre cuotas de fútbol en casas de apuestas españolas: ¿hay cuotas mal puestas que se puedan aprovechar de forma sistemática? Incluye un bot que compara cuotas en tiempo casi real y avisa por Telegram de *value bets* y *surebets*.

**Estado: proyecto cerrado, sin éxito.** El estudio con datos históricos dio señales de ventaja, pero en la prueba con datos en directo el bot no encontró ni una oportunidad y no fue posible comprobar que las cuotas de la API coincidieran con las de las webs. Se publica como ejemplo de análisis completo de principio a fin, incluida la parte en que la hipótesis no se sostiene.

El bot nunca apuesta: solo detecta, registra y avisa.

## La pregunta

Una casa de apuestas "sharp" como Pinnacle tiene cuotas muy precisas. Si se le quita el margen (*devig*), se obtiene una estimación de la probabilidad real de cada resultado: la **cuota justa**. Cuando una casa "blanda" con licencia en España (Winamax, Codere, bet365, Betway, Bwin) paga por encima de esa cuota justa, la apuesta tiene valor esperado positivo (*value bet*). Si combinando varias casas se cubren todos los resultados con `sum(1/cuota) < 1`, el beneficio está garantizado (*surebet*).

La métrica para saber si la ventaja es real es el **CLV** (*Closing Line Value*): si las cuotas señaladas son sistemáticamente mejores que la cuota justa de Pinnacle al inicio del partido, hay ventaja, aunque los resultados a corto plazo digan otra cosa.

## Datos

- **OddsPapi**: cuotas de Pinnacle y de las casas `.es`. Su endpoint de histórico no consume cupo y devuelve cada cambio de cuota desde la apertura hasta el inicio del partido. El plan gratuito permite 250 peticiones al mes para las cuotas actuales.
- **The Odds API**: fuente de respaldo, evaluada en la fase de selección de fuentes.
- Histórico descargado: **622 partidos** de LaLiga y Premier League (enero a noviembre de 2026), unos 650 MB en SQLite. No se incluye en el repositorio; se regenera con `scripts/estudio_descarga.py`.

Comparativa de fuentes en [docs/fuentes.md](docs/fuentes.md).

## Resultados

### 1. Estudio histórico: prometedor

Detalle en [docs/estudio_viabilidad.md](docs/estudio_viabilidad.md) y [docs/estudio_viabilidad_datos.md](docs/estudio_viabilidad_datos.md).

- **El 1X2 no da ventaja.** CLV negativo o nulo en todas las casas.
- **Más/Menos (líneas .5) y Ambos marcan sí.** CLV medio de +3 a +5 % con edge de al menos 3 %, estable entre la primera y la segunda mitad del año.
- **Consultar cada 30 minutos basta**: capta el 85-90 % del valor de consultar cada 5.
- Escenario estimado: unas 140 apuestas al mes, y con 20 € por apuesta, entre +50 y +95 €/mes una vez pagada la API (~85 $/mes).

### 2. Corrección: cuotas congeladas

Detalle en [docs/estudio_frescura_datos.md](docs/estudio_frescura_datos.md).

Al probar el bot aparecieron alertas con cuotas que llevaban días sin moverse. El CLV no sirve para detectarlas: una cuota congelada por encima de la justa sale con CLV positivo aunque ya no se pueda apostar. En Winamax, la mediana de antigüedad del mercado al abrirse la oportunidad era de **133 horas**. Al quedarse solo con mercados vivos (algún cambio en las últimas 24 h):

| Casas | Apuestas/mes | €/mes a 10 €/apuesta |
|---|---|---|
| Winamax + Codere | 28 | +15 a +17 |
| Winamax + Codere + bet365 | 100 | +50 a +67 |

La ventaja se mantiene, pero el volumen cae y **todo depende de bet365**. El punto de equilibrio sube a unos 16 € por apuesta.

### 3. Surebets: pocas y pequeñas

Detalle en [docs/estudio_surebets_datos.md](docs/estudio_surebets_datos.md).

Unas 14 surebets aprovechables al mes entre las cinco casas, con un beneficio garantizado medio del 1,9 %. Con 100 € por surebet, unos +26 €/mes.

### 4. Prueba en directo: sin oportunidades

Con el bot ya funcionando, se lanzaron consultas reales en noviembre de 2026 (unos 40 partidos en cada una, de los que 18 caían en la ventana de 0 a 72 h). Resultado: **0 value bets y 0 surebets**. Una consulta de diagnóstico mostró por qué:

- **bet365 venía suspendido** (`suspended: true`, `bookmakerIsActive: false`) en 16 de los 18 partidos dentro de la ventana. En el histórico sí tenía datos. Sin bet365 desaparece la mayor parte de la ventaja estimada.
- **Winamax y Codere estaban por debajo de la cuota justa** en todas las selecciones comparadas (292). La mejor se quedaba en un edge de -1,4 %, frente al +3 % exigido. La mediana, entre -5 y -7 %, es el margen normal de la casa.
- Con el histórico, sin bet365 y con cuatro consultas al día, se esperan unas **0,3 alertas al día**. La prueba prevista (15-20 alertas comprobadas a mano en la web) no era viable con el plan gratuito.

## Por qué se abandona

1. **No se pudo validar la premisa básica**: que las cuotas que da la API para las casas `.es` son las que se pueden apostar en sus webs. Sin esa comprobación, el CLV del histórico no demuestra que el dinero estuviera disponible.
2. **La casa imprescindible no llega en directo** con el plan gratuito, y pagar ~85-115 $/mes sin haber validado nada era una apuesta en sí misma.
3. **El margen era fino incluso en el escenario bueno**: hacían falta 16-20 € por apuesta solo para cubrir la API, con mucha varianza mensual.
4. **Limitación de cuentas**: las casas limitan pronto a quien gana con value betting o arbitraje. El escenario rentable habría durado meses, no años.

## Qué se puede reutilizar

- Cliente de OddsPapi con pausas por endpoint, reintentos y control de cupo (`src/bot_apuestas/oddspapi.py`).
- Devig multiplicativo y power, y cálculo de edge (`devig.py`).
- Reconstrucción de oportunidades sobre un histórico de cambios de cuota, con duración, CLV y probabilidad de captura según la frecuencia de consulta (`estudio.py`).
- Detección de cuotas desfasadas por antigüedad del mercado.
- Detector de surebets con reparto de stakes y alertas a Telegram.

## Estructura

```
src/bot_apuestas/
  __main__.py   # CLI: once / run / clv / report / status / telegram-chat-id
  config.py     # configuración desde .env (variables BOT_*)
  oddspapi.py   # cliente HTTP con pausas y reintentos
  catalog.py    # catálogo de mercados y equipos (caché semanal)
  detector.py   # parseo de cuotas, value bets y surebets
  devig.py      # cuota justa y edge
  store.py      # SQLite: alertas, surebets, CLV y registro de consultas
  telegram.py   # formato y envío de alertas
  clv.py        # CLV de las alertas ya jugadas
  muestra.py    # CSV para comprobar alertas a mano
  estudio.py    # reconstrucción de oportunidades en el histórico
scripts/        # descarga del histórico y análisis del estudio
tests/          # tests con respuestas grabadas, sin llamadas a las APIs
docs/           # fuentes, estudio de viabilidad, frescura y surebets
```

Stack: Python 3.12 o superior, `httpx`, `python-dotenv`, `tzdata`. SQLite con `sqlite3`, sin ORM. Desarrollo: `pytest` y `ruff`.

## Instalación y uso

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # Windows; en Linux/macOS, .venv/bin/python
cp .env.example .env                                  # y rellenar ODDSPAPI_KEY
.venv/Scripts/python -m pytest -q
```

Estudio (el histórico es gratuito en OddsPapi, pero la descarga tarda unas 2 horas):

```bash
.venv/Scripts/python scripts/estudio_descarga.py     # reanudable
.venv/Scripts/python scripts/estudio_analisis.py
.venv/Scripts/python scripts/estudio_frescura.py
.venv/Scripts/python scripts/estudio_surebets.py
```

Bot:

```bash
.venv/Scripts/python -m bot_apuestas status    # cupo restante (gratis)
.venv/Scripts/python -m bot_apuestas once      # una consulta (6 peticiones: Pinnacle + 5 casas)
.venv/Scripts/python -m bot_apuestas run       # bucle cada 30 min (requiere plan de pago)
.venv/Scripts/python -m bot_apuestas clv       # CLV de las alertas ya jugadas (gratis)
.venv/Scripts/python -m bot_apuestas report    # resumen de alertas
```

Para recibir las alertas por Telegram: crear un bot con @BotFather, poner el token en `TELEGRAM_BOT_TOKEN`, escribirle un mensaje y ejecutar `python -m bot_apuestas telegram-chat-id` para obtener `TELEGRAM_CHAT_ID`. Sin Telegram, las alertas salen por consola.

## Aviso

Esto es un análisis de datos, no asesoramiento financiero ni una invitación a apostar. Apostar implica riesgo de pérdida. Las cifras económicas son estimaciones sobre datos históricos y no se confirmaron en la prueba en directo.
