# Fase 0: fuentes de datos

_Investigación del 15-11-2026. Los precios y la cobertura cambian: se vuelven a comprobar al crear las cuentas._

## Resumen y decisión provisional

| Papel | Fuente | Por qué |
|---|---|---|
| **Cuotas de casas españolas (.es)** | **OddsPapi** (candidata principal) | Es la única que ofrece casas `.es` **y** Pinnacle en la misma API, y el histórico es gratis. Falta confirmar el límite del plan gratuito al registrarse. |
| **Referencia sharp** | Pinnacle (vía OddsPapi o The Odds API) + **Betfair Exchange API** (oficial) | La API oficial de Pinnacle está cerrada al público desde el 23-07-2025. Betfair da precios del exchange con liquidez. |
| **Respaldo gratuito** | **The Odds API** (500 créditos/mes gratis) | Sirve para la referencia sharp (Pinnacle, Betfair Exchange EU), pero **no tiene ninguna casa .es**. |
| Plan de pago si OddsPapi no sirve | odds-api.io | Tiene la mejor cobertura `.es` (14 casas), pero no tiene Pinnacle, el plan gratuito está pausado y el plan de pago cobra por número de casas (desde 49 £/mes por 2 casas). |

Conclusión: **no hace falta scraping propio de momento.** Las casas `.es` importantes aparecen en APIs comerciales. El scraping (vía C: conectores propios contra cada casa) queda solo para huecos, como Sportium, que no aparece en versión `.es` en ninguna API revisada.

## Comparativa

| | The Odds API | OddsPapi | odds-api.io | Betfair Exchange API |
|---|---|---|---|---|
| Casas `.es` | Ninguna | 9 con cuotas en vivo de LaLiga: bet365.es, bwin.es, codere.es, winamax.es, 888sport.es, betway.es, leovegas.es, paf.es, pokerstars.es | 14: Bet365 ES, Bwin ES, Codere ES, Winamax ES, Betfair ES, Retabet ES, Luckia ES, DAZN Bet ES, 888Sport ES, Betway ES, Casumo ES, LeoVegas ES, PAF ES, PokerStars ES | Solo su propio exchange (betfair.es) |
| Pinnacle | Sí (sacada de su web pública, con retraso) | Sí | No | — |
| Betfair Exchange | Sí (`betfair_ex_eu`) | Sí (`betfair-ex`) | Sí | Sí, oficial |
| Plan gratuito | 500 créditos/mes | Existe; límite mensual por confirmar | Pausado para claves nuevas | *Delayed key* gratuita (retraso de 1-180 s, sin volumen casado) |
| Pago | 30 $/mes (20K créditos), 59 $ (100K), 119 $ (5M) | Precio no visible sin registrarse | 49 £ (2 casas), 99 £ (5), 179 £ (10), 229 £ (15) | Clave en vivo: 299 £ una sola vez |
| Coste de una petición | 1 crédito por mercado y región (10 casas = 1 región) | 1 petición por llamada | Peticiones por hora (5.000/h en los planes de pago) | — |
| Frecuencia | 60 s antes del partido, 40 s en directo; exchanges 20 s / 10 s | REST (consultas cada 10-60 s) + WebSocket; ~1 s en las principales | REST + WebSocket (complemento de pago) | REST + Stream |
| Histórico | Planes de pago (desde junio de 2020, snapshots cada 5 min, cuesta 10×) | **Gratis** (`/v4/historical-odds`, máximo 3 casas por llamada) | — | Datos históricos aparte |
| Auth | `apiKey` en la URL | `apiKey` en la URL | `apiKey` en la URL | App key + login de sesión |

## Resultados con datos reales (15-11-2026, LaLiga + Premier, 40 partidos)

### The Odds API (gratis, 4 créditos por ejecución; quedan 496/500)
- 24 casas, **ninguna `.es`** (aparece `codere_it`, que es la versión italiana).
- Margen medio 1X2: Pinnacle 4,35 %, Marathonbet 4,31 %, William Hill 7,63 %, Winamax DE 8,38 %; las casas francesas (Winamax FR, Unibet FR, PMU) pasan del 14 %.
- Detectó 10 "surebets" 1X2, **todas falsas** en la práctica: usan exchanges (Betfair, Matchbook) sin descontar su comisión, o 1xBet, que no tiene licencia en España. **Lección para la Fase 3:** descontar la comisión de los exchanges y considerar solo casas en las que se pueda apostar.
- Betfair Exchange da precios *back* y *lay* (`h2h_lay`) con poco diferencial en los partidos con liquidez. Su margen "medio" (14,6 %) sale inflado por mercados sin liquidez: hay que filtrarlos por liquidez.

### OddsPapi (gratis)
- **Plan gratuito: 250 peticiones al mes, solo prepartido (sin cuotas en directo ni WebSocket).** Esta prueba gastó unas 12. El histórico (`/v4/historical-odds`) no consume cupo.
- Hay que esperar ~2 s entre peticiones (si no, devuelve HTTP 429): el script ya lo hace.
- Catálogo `.es`: 888sport, bet365, betfair, betway, bwin, codere, leovegas, paf, pokerstars, winamax.
- **Gran ventaja:** el `fixtureId` es el mismo en todas las casas. OddsPapi ya empareja los partidos y usa IDs de mercado comunes (101 = 1X2, 1010 = Más/Menos 2.5), así que **la Fase 2 (emparejamiento) se simplifica mucho** si usamos esta fuente.
- Formato: `fixture → bookmakerOdds[casa] → markets[marketId] → outcomes[outcomeId] → players["0"] → price, active, changedAt`. Catálogo de mercados en `/v4/markets?sportId=10`.

| Casa | Partidos | 1X2 activo | Margen 1X2 | Más/Menos 2.5 activo | Margen O/U 2.5 |
|---|---|---|---|---|---|
| pinnacle | 40 | 40 | 4,38 % | 38 | 4,36 % |
| winamax.es | 40 | 40 | 8,38 % | 20 | 5,83 % |
| bet365.es | 34 | 8 (el resto, suspendidos a 1,01) | 8,93 % | 8 | 5,61 % |
| codere.es | 40 | **0** (no viene el mercado 1X2) | — | 40 | 8,26 % |
| bwin.es | 20 | **0** (no viene el mercado 1X2) | — | 17 | 7,77 % |

- Value > 2 % frente a Pinnacle sin margen (devig multiplicativo): 1 en 1X2 y 3 en Más/Menos 2.5, todas en Winamax.es (hasta +8,2 %). **No están validadas**: pueden ser cuotas desfasadas (hay que mirar `changedAt`) o Pinnacle puede ir con retraso.
- El margen de Pinnacle (~4,4 %) es más alto de lo esperable (~2,5-3 % en ligas top): puede que la fuente no sea la línea principal más reciente. Hay que contrastarlo con Betfair Exchange.

### Conclusiones
1. **OddsPapi sirve como fuente principal**, pero el plan gratuito (250 peticiones/mes) solo da para pruebas: con 5 casas × 2 ligas, una foto cuesta ~5 peticiones, así que salen ~50 fotos al mes. Para la Fase 1 en continuo hará falta plan de pago (precio por confirmar en su web, con la sesión iniciada).
2. **Codere y Bwin no traen el 1X2** y **bet365 lo trae casi todo suspendido**: hay que preguntar a OddsPapi o mirar si es cosa del plan gratuito o de la hora (domingo por la tarde, 5 días antes de los partidos).
3. **The Odds API** se queda como referencia sharp gratuita y como comprobación cruzada de Pinnacle.
4. **Betfair Exchange API**: conviene tenerla antes de la Fase 3, para tener una segunda referencia de precio justo.

## Lagunas y riesgos

- **Sportium** no aparece en versión `.es` en ninguna API (solo "Sportium IT" en odds-api.io). **Kirolbet** y **Marca Apuestas** tampoco han aparecido.
- **Las cuotas `.es` pueden diferir de las `.com`.** Hay que comprobarlo con la muestra manual (`docs/prueba_alertas.csv`).
- La Pinnacle de The Odds API se saca de la web pública "con posible retraso": para value bets en directo no sirve, para prepartido sí.
- Toda la información de OddsPapi y odds-api.io viene de sus propias webs y blogs (marketing): hay que validarla con datos reales.

## Pasos pendientes (manuales)

1. Crear una cuenta gratuita en **OddsPapi** (oddspapi.io) y anotar el límite mensual del plan gratuito → `ODDSPAPI_KEY` en `.env`.
2. Crear una cuenta gratuita en **The Odds API** (the-odds-api.com) → `ODDS_API_KEY` en `.env`.
3. *(Opcional en esta fase)* Crear una cuenta en betfair.es y generar la *delayed app key*.
4. Ejecutar `scripts/fase0_descarga.py` (ver el README) y revisar el resumen de cobertura.
5. Rellenar `docs/prueba_alertas.csv`: 20-30 cuotas de la API comparadas a mano con la web `.es`, a la misma hora.

## Fuentes consultadas
- https://the-odds-api.com/sports-odds-data/bookmaker-apis.html
- https://the-odds-api.com/sports-odds-data/update-intervals.html
- https://oddspapi.io/blog/la-liga-odds-api/
- https://oddspapi.io/us/docs/requests-and-quota
- https://odds-api.io/sportsbooks/europe
- https://github.com/pinnacleapi/pinnacleapi-documentation (cierre de la API de Pinnacle)
- https://betfair-developer-docs.atlassian.net/ (app keys y cuentas españolas)
