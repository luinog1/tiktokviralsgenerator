# Fontes do renderer

O `SlideRenderer` procura estes dois arquivos antes de qualquer fonte do sistema
(ver `_BOLD_CANDIDATES` / `_REGULAR_CANDIDATES` em `app/services/slide_renderer.py`).

| Arquivo | Corte | Usado em |
|---------|-------|----------|
| `sticker-bold.ttf` | TikTok Sans **SemiBold** (wght 600) | headline e CTA |
| `sticker-regular.ttf` | TikTok Sans **Medium** (wght 500) | corpo do texto |

É a tipografia oficial do TikTok — substituiu a Poppins, que era só uma
aproximação geométrica.

## Como foram geradas

O Google Fonts publica TikTok Sans **apenas como fonte variável**
(`TikTokSans[opsz,slnt,wdth,wght].ttf`), e o default do eixo de peso é
**Light 300**. Soltar esse arquivo direto renderizaria o slide fino demais — o
Pillow carrega a instância default e não interpola sozinho.

Os dois arquivos aqui são instâncias estáticas geradas com `fontTools`:

```python
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

font = TTFont("TikTokSans[opsz,slnt,wdth,wght].ttf")
instantiateVariableFont(font, {"wght": 600, "opsz": 36, "wdth": 100, "slnt": 0}, inplace=True)
font.save("sticker-bold.ttf")
```

`opsz` fica travado em 36 (topo do eixo = tamanho de texto grande, que é o caso
do slide), `wdth` em 100 e `slnt` em 0. Só o peso muda entre os dois cortes.

Os registros de nome (nameIDs 1/2/4/6/16/17) e o `OS/2.usWeightClass` também são
reescritos — sem isso a instância continua se identificando como "Light".

`fontTools` é dependência **só desse processo**, não da aplicação. Não está em
`requirements.txt`.

## Trocar a tipografia

Substitua os dois arquivos (qualquer `.ttf` estático) ou aponte
`SLIDE_FONT_BOLD` / `SLIDE_FONT_REGULAR` para outros caminhos.

Licença: SIL Open Font License 1.1 — ver `OFL.txt`. Copyright 2024 TikTok Inc.,
distribuída via [Google Fonts](https://fonts.google.com/specimen/TikTok+Sans) e
[github.com/tiktok/TikTokSans](https://github.com/tiktok/TikTokSans).
