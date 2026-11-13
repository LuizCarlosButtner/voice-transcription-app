import subprocess
from pathlib import Path

from PIL import Image, ImageDraw


def gerar_icone_aplicativo(caminho_saida_icns: Path) -> None:
    """Gera o arquivo de ícone `.icns` do aplicativo para macOS em múltiplas resoluções."""
    diretorio_conjunto_icones = caminho_saida_icns.parent / "AppIcon.iconset"
    diretorio_conjunto_icones.mkdir(parents=True, exist_ok=True)

    # Cria tela base 1024x1024 com canal alfa transparente
    dimensao_base = 1024
    imagem_base = Image.new("RGBA", (dimensao_base, dimensao_base), (0, 0, 0, 0))
    desenhador = ImageDraw.Draw(imagem_base)

    # 1. Quadro arredondado de fundo no padrão macOS
    x_inicial, y_inicial, x_final, y_final = 60, 60, 964, 964
    raio_canto = 210

    # Fundo escuro azulado e índigo profundo
    desenhador.rounded_rectangle(
        [x_inicial, y_inicial, x_final, y_final],
        radius=raio_canto,
        fill=(28, 25, 75, 255),
        outline=(99, 102, 241, 180),
        width=8,
    )

    # Círculo de brilho central
    desenhador.ellipse([260, 260, 764, 764], fill=(49, 46, 129, 255))

    # 2. Desenho da cápsula central do microfone
    centro_x, centro_y = 512, 450
    largura_microfone, altura_microfone = 140, 260
    desenhador.rounded_rectangle(
        [
            centro_x - largura_microfone // 2,
            centro_y - altura_microfone // 2,
            centro_x + largura_microfone // 2,
            centro_y + altura_microfone // 2,
        ],
        radius=70,
        fill=(245, 245, 255, 255),
    )

    # Grelha horizontal sutil na cápsula do microfone
    for deslocamento_y in (-40, 0, 40):
        desenhador.line(
            [
                centro_x - largura_microfone // 2 + 20,
                centro_y + deslocamento_y,
                centro_x + largura_microfone // 2 - 20,
                centro_y + deslocamento_y,
            ],
            fill=(180, 185, 220, 255),
            width=6,
        )

    # Arco de suporte do microfone
    largura_arco = 230
    desenhador.arc(
        [
            centro_x - largura_arco // 2,
            centro_y - 20,
            centro_x + largura_arco // 2,
            centro_y + 190,
        ],
        start=0,
        end=180,
        fill=(255, 255, 255, 255),
        width=24,
    )

    # Haste vertical e base inferior do microfone
    desenhador.line(
        [centro_x, centro_y + 190, centro_x, centro_y + 280],
        fill=(255, 255, 255, 255),
        width=24,
    )
    desenhador.rounded_rectangle(
        [centro_x - 90, centro_y + 280, centro_x + 90, centro_y + 304],
        radius=12,
        fill=(255, 255, 255, 255),
    )

    # 3. Ondas acústicas radiantes nas laterais
    cor_onda_primaria = (129, 140, 248, 230)
    cor_onda_secundaria = (192, 132, 252, 200)

    # Lateral esquerda
    desenhador.arc(
        [centro_x - 320, centro_y - 100, centro_x - 180, centro_y + 180],
        start=110,
        end=250,
        fill=cor_onda_primaria,
        width=18,
    )
    desenhador.arc(
        [centro_x - 400, centro_y - 150, centro_x - 220, centro_y + 230],
        start=115,
        end=245,
        fill=cor_onda_secundaria,
        width=14,
    )

    # Lateral direita
    desenhador.arc(
        [centro_x + 180, centro_y - 100, centro_x + 320, centro_y + 180],
        start=-70,
        end=70,
        fill=cor_onda_primaria,
        width=18,
    )
    desenhador.arc(
        [centro_x + 220, centro_y - 150, centro_x + 400, centro_y + 230],
        start=-65,
        end=65,
        fill=cor_onda_secundaria,
        width=14,
    )

    # 4. Exporta todas as resoluções exigidas pelo macOS
    resolucoes_icone = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]

    for dimensao, nome_arquivo in resolucoes_icone:
        imagem_redimensionada = imagem_base.resize(
            (dimensao, dimensao), Image.Resampling.LANCZOS
        )
        imagem_redimensionada.save(diretorio_conjunto_icones / nome_arquivo, "PNG")

    # 5. Converte o conjunto de imagens para `.icns` usando `iconutil`
    comando_conversao = [
        "iconutil",
        "-c",
        "icns",
        str(diretorio_conjunto_icones),
        "-o",
        str(caminho_saida_icns),
    ]
    subprocess.run(comando_conversao, check=True)

    # Remove arquivos temporários após consolidar o `.icns`
    for arquivo_png in diretorio_conjunto_icones.glob("*.png"):
        arquivo_png.unlink()
    diretorio_conjunto_icones.rmdir()
    print(f"[OK] AppIcon.icns gerado com sucesso em: {caminho_saida_icns}")


if __name__ == "__main__":
    caminho_saida_padrao = Path(__file__).resolve().parent / "AppIcon.icns"
    gerar_icone_aplicativo(caminho_saida_padrao)
