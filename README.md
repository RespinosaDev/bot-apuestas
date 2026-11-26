# Análisis de cuotas de apuestas

Proyecto personal. Quería ver si las casas de apuestas españolas ponen cuotas de fútbol mal ajustadas que se puedan aprovechar de forma sistemática (value bets y surebets). Para eso descargué un histórico de cuotas, lo analicé y monté un bot que avisa por Telegram de las oportunidades. El bot no apuesta, solo avisa.

El proyecto salió mal: el histórico parecía prometedor, pero con datos en directo no apareció ninguna oportunidad, así que lo dejé como análisis de datos.

## Herramientas

Python, httpx, SQLite, la API de OddsPapi, la API de Telegram y pytest.

## Cómo funciona

Se toma Pinnacle como referencia, porque sus cuotas son muy precisas. Se le quita el margen para obtener la cuota justa de cada resultado y se compara con las cuotas de Winamax, Codere, bet365, Betway y Bwin. Si una casa paga claramente más que la cuota justa, es una value bet; si combinando casas se gana pase lo que pase, es una surebet. Para saber si la ventaja es real se mira el CLV, que compara la cuota que avisa el bot con la cuota de Pinnacle al empezar el partido.

## Requisitos

- Python 3.12 o superior
- Las dependencias de `pyproject.toml`
- Una clave de OddsPapi en `.env` (ver `.env.example`); Telegram es opcional

## Resultados

- Histórico de 622 partidos de LaLiga y Premier League: en Más/Menos y Ambos marcan salía un CLV de +3 a +5 %. En el 1X2 no había ventaja.
- Muchas de esas oportunidades eran cuotas congeladas que llevaban días sin moverse. Quitándolas quedaban unas 100 apuestas al mes, y casi todas dependían de bet365.
- En directo, con el plan gratuito de la API, bet365 venía suspendido y en Winamax y Codere ninguna cuota superaba la justa. Resultado: 0 alertas.

Sin poder comprobar que las cuotas de la API estaban de verdad en las webs, no tenía sentido pagar el plan de la API (unos 85 $ al mes). El análisis completo está en la carpeta `docs/`.
