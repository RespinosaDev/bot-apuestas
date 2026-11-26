# Fase 0.5: estudio de viabilidad, conclusiones

_15-11-2026. Datos: histórico completo de cuotas (cada cambio, desde la apertura hasta el inicio) de **622 partidos** de LaLiga y Premier League jugados entre el 01-01-2026 y el 08-11-2026, para Pinnacle y 5 casas `.es`. Coste: 2 peticiones del plan gratuito de OddsPapi. Números completos en [estudio_viabilidad_datos.md](estudio_viabilidad_datos.md)._

## Veredicto: **sigue adelante, con condiciones**

Hay ventaja medible y estable en algunas casas y mercados españoles frente a Pinnacle. Con stakes de 10 € apenas cubre el coste de la API: el proyecto solo tiene sentido económico con **~20 € o más por apuesta** y aceptando que las casas acabarán limitando las cuentas.

## Qué dicen los datos

1. **El 1X2 no sirve.** En bet365, Betway y Bwin el CLV es negativo. En Winamax y Codere es ~0 con el devig conservador (power). Las "ventajas" en 1X2 suelen ser líneas tempranas que Pinnacle corrige después en contra.
2. **Más/Menos (líneas .5) y Ambos marcan sí sirven.** CLV medio de +2 % a +8 % según casa y mercado, con un 70-90 % de oportunidades con CLV positivo, y siguen positivas con el devig power.
3. **Es estable en el tiempo.** Winamax + Codere + bet365, mercados fiables, edge ≥ 3 %:
   - enero-mayo: CLV +4,2 % (power +3,1 %)
   - agosto-noviembre: CLV +5,5 % (power +3,9 %)
4. **La antelación importa.** Con más de 3 días de antelación (Pinnacle aún con límites bajos), el CLV es ~0-1,5 %. **Lo bueno está entre 6 horas y 3 días antes del partido** (CLV +5-8 % en Winamax, Codere y Bwin).
5. **Casi no hace falta tiempo real.** Consultar cada 30 minutos captura ~85-90 % del valor de consultar cada 5. Basta el plan barato de 5.000 peticiones.
6. **Por casa:** Winamax y bet365 son las mejores (muchas oportunidades y largas). Codere tiene buen CLV, pero sus oportunidades duran poco (mediana de 2-5 min). Betway es casi irrelevante.

## Corrección (15-11-2026): cuotas desfasadas

Al probar el bot salieron alertas de Winamax con cuotas que no cambiaban desde hacía 12 días. Revisión en [estudio_frescura_datos.md](estudio_frescura_datos.md) (`scripts/estudio_frescura.py`):

- **El CLV no sirve para detectar cuotas desfasadas.** Si una casa deja congelada una cuota por encima de la cuota justa, su CLV sale positivo igual, porque Pinnacle no "vuelve" de media. El CLV positivo confirma que Pinnacle es buena referencia y que la cuota estaba por encima de la justa, **no** que se pudiera apostar.
- **Antigüedad típica del mercado de la casa al abrirse la oportunidad:** bet365 0 h, Codere 0,1 h, Bwin 9 h, **Winamax 133 h**. La mayor parte del "valor" de Winamax viene de mercados que llevaban más de 3 días sin moverse en OddsPapi.
- Las oportunidades con mercado vivo (algún cambio en las últimas 24 h) mantienen el CLV (+3-6 %): **la ventaja no es un artefacto**, pero hay menos volumen.
- **Escenario corregido** (solo mercados vivos, consulta cada 30 min, 10 €/apuesta):

| Casas | Apuestas/mes | €/mes (power / mult.) |
|---|---|---|
| Winamax + Codere | 28 | +15 / +17 |
| Winamax + Codere + bet365 | 100 | **+50 / +67** |
| Codere + bet365 (~75 $/mes) | 86 | +42 / +56 |
| Winamax + Codere + bet365 + Bwin | 111 | +58 / +76 |

**Consecuencias:** bet365 es imprescindible. Winamax aporta poco una vez quitadas las cuotas antiguas. Con ~80 €/mes de API, el punto de equilibrio sube a **~16 € por apuesta**: con 20 € saldría ≈ +20 a +55 €/mes, y con 30 €, ≈ +70 a +120 €/mes. El bot descarta ya los mercados sin cambios en más de 24 h (`BOT_MAX_MARKET_AGE_H`). Las cifras del escenario siguiente quedan como estaban antes de esta corrección.

## Surebets entre casas españolas (15-11-2026)

Medido en el mismo histórico, sin Pinnacle (no hace falta referencia): [estudio_surebets_datos.md](estudio_surebets_datos.md) (`scripts/estudio_surebets.py`). Solo cuentan las surebets con mercados vivos (cambio < 24 h en cada casa):

- **~14 surebets aprovechables al mes** (LaLiga + Premier), con un beneficio garantizado medio de **~1,9 %** (mediana 1,1 %, p90 5 %). Duración mediana: 25 min. Consultar cada 30 min capta casi todas.
- Con 100 € repartidos por surebet: **+26 €/mes**. Escala con lo que se reparte: con 300 € por surebet, ~+78 €/mes.
- Pares que más aparecen: **Betway + Codere**, bet365 + Winamax, Betway + Bwin. Betway y Bwin, irrelevantes para el value betting, son clave aquí.
- El mejor mercado es Más/Menos (.5): 2 % de media, ~1 h de duración. Ambos marcan dura poco (5 min).

**Comparación con el value betting:** el value bet rinde ~5 % por euro apostado frente al ~1,9 % de la surebet, pero tiene mucha varianza. La surebet tiene casi ninguna, en teoría: siguen existiendo el riesgo de que cambie la segunda cuota, las anulaciones por error palpable y las reglas distintas entre casas. Son complementarios: el mismo bot puede avisar de las dos cosas. Las surebets necesitan Betway ES (10 $) y Bwin ES (20 $) en el plan, pero no Pinnacle.

## Escenario recomendado (antes de la corrección)

| | |
|---|---|
| Casas | Winamax.es + Codere.es + bet365.es (+ Betfair ES gratis) |
| Plan OddsPapi | Pinnacle +30 s (30 $) + Winamax ES (10 $) + Codere ES (10 $) + bet365 ES (30 $) + fútbol (5 $) = **~85 $/mes** (~80 €) |
| Peticiones | 4 por foto × cada 30 min × 15 h/día ≈ 3.600/mes (< 5.000) |
| Mercados | Más/Menos (líneas .5) y Ambos marcan; edge ≥ 3 %; de 6 h a 3 días antes del partido |
| Volumen esperado | ~140 apuestas/mes (~4-5 al día), cuota mediana 2,4 |
| Beneficio esperado con 10 €/apuesta | +66 a +87 €/mes (power / multiplicativo) → **≈ coste de la API** |
| Con 20 €/apuesta | +130 a +175 €/mes − 80 € de API = **+50 a +95 €/mes** |
| Con 30 €/apuesta | +200 a +260 €/mes − 80 € = **+120 a +180 €/mes** |

## Riesgos (por orden de importancia)

1. **Limitación de cuentas.** Winamax y bet365 limitan rápido a quien gana con value betting; Codere también. Cuando limitan el stake máximo a 1-5 €, ese escenario deja de cubrir la API. Es el riesgo que decide la vida útil del proyecto: meses, no años.
2. **Varianza.** Con ~140 apuestas de 20 € al mes, la desviación típica mensual es de ~250-300 €, mayor que el beneficio esperado. Un mes en negativo no significa nada; hay que juzgar por el **CLV**, que converge mucho antes que el beneficio.
3. **Fidelidad de los datos.** Falta comprobar que las cuotas de OddsPapi para `.es` coinciden con las que ves en la web (muestra manual de la Fase 0) y cuánto se pierde entre la alerta y el clic.
4. **Referencia.** El "pinnacle" de OddsPapi puede llevar retraso. Las oportunidades apartadas por edge > 30 % (~180) son probables errores de datos, no dinero.
5. **Supuestos del modelo.** Reacción de 3 min, una apuesta por selección, 80 partidos/mes (LaLiga + Premier en temporada; menos en parones y en verano).

## Siguientes pasos propuestos

1. **(Gratis, manual)** Muestra manual: 20-30 cuotas de Winamax/Codere/bet365 en la web `.es` frente a OddsPapi, a la misma hora → `docs/prueba_alertas.csv`.
2. **Construir el bot mínimo** (Fases 1-4 reducidas): consulta cada 30 min, detector con estos filtros, alertas a Telegram y registro de cada alerta con su CLV posterior. El código de este estudio (devig, detector) se reutiliza.
3. **1-2 meses de prueba con el plan de ~85 $**, apostando a mano con stakes pequeños y midiendo el CLV real, el % de alertas que siguen vivas al abrir la casa y cuándo limitan. Seguir o parar se decide por el CLV real, no por el saldo.
4. Ampliar ligas (Serie A, Bundesliga, Ligue 1: mismo coste de 5 $/deporte, más partidos al mes) es la forma más barata de subir el volumen.

_Esto es un análisis de datos, no asesoramiento financiero. Apostar implica riesgo de pérdida; decide el bankroll que puedes permitirte perder._

## Cierre del proyecto (26-11-2026)

La prueba con datos en directo no confirmó el estudio. En las consultas reales de noviembre no salió ninguna oportunidad: bet365 venía suspendido en OddsPapi en 16 de los 18 partidos de las próximas 72 h, y en Winamax y Codere ninguna cuota superaba la cuota justa de Pinnacle (la mejor, edge -1,4 %). Según el histórico, sin bet365 y con cuatro consultas al día se esperan unas 0,3 alertas al día, así que no fue posible comprobar a mano que las cuotas de la API existieran en las webs. Sin esa validación no tiene sentido pagar la API. El proyecto se cierra como análisis de datos; el resumen está en el README.
