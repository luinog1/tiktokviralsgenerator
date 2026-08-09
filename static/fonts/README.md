# Fontes do renderer

O `SlideRenderer` procura estes dois arquivos antes de qualquer fonte do sistema
(ver `_BOLD_CANDIDATES` / `_REGULAR_CANDIDATES` em `app/services/slide_renderer.py`).

| Arquivo | Fonte original | Usado em |
|---------|----------------|----------|
| `sticker-bold.ttf` | Poppins SemiBold | headline e CTA |
| `sticker-regular.ttf` | Poppins Medium | corpo do texto |

Poppins é uma geométrica — é o que aproxima os slides da tipografia dos photo
posts do TikTok. Os pesos SemiBold/Medium foram escolhidos no lugar de
Bold/Regular porque o texto nativo do TikTok é de peso médio: Bold fica pesado
demais na caixa branca e Regular fica fino demais sobre a foto.

Para trocar a tipografia, substitua os dois arquivos (qualquer `.ttf`) ou aponte
`SLIDE_FONT_BOLD` / `SLIDE_FONT_REGULAR` para outros caminhos.

Licença: SIL Open Font License 1.1 — ver `OFL.txt`. Copyright Indian Type
Foundry, distribuída via [Google Fonts](https://fonts.google.com/specimen/Poppins).
