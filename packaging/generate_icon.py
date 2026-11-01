import os
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw

def generate_app_icon(output_icns_path: Path):
    iconset_dir = output_icns_path.parent / "AppIcon.iconset"
    iconset_dir.mkdir(parents=True, exist_ok=True)

    # Cria base 1024x1024 com antialiasing
    size = 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Squircle de fundo macOS com gradiente sutil
    # Cantos arredondados raio ~220px
    x0, y0, x1, y1 = 60, 60, 964, 964
    radius = 210

    # Fundo escuro azulado / roxo profundo (#1E1B4B -> #312E81)
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=(28, 25, 75, 255), outline=(99, 102, 241, 180), width=8)

    # Circulo de brilho central
    draw.ellipse([260, 260, 764, 764], fill=(49, 46, 129, 255))

    # 2. Desenho do Microfone (cápsula branca com realce ciano/índigo)
    # Corpo do mic (cápsula)
    cx, cy = 512, 450
    mw, mh = 140, 260
    draw.rounded_rectangle([cx - mw//2, cy - mh//2, cx + mw//2, cy + mh//2], radius=70, fill=(245, 245, 255, 255))

    # Grelha / detalhes horizontais sutis no mic
    draw.line([cx - mw//2 + 20, cy - 40, cx + mw//2 - 20, cy - 40], fill=(180, 185, 220, 255), width=6)
    draw.line([cx - mw//2 + 20, cy, cx + mw//2 - 20, cy], fill=(180, 185, 220, 255), width=6)
    draw.line([cx - mw//2 + 20, cy + 40, cx + mw//2 - 20, cy + 40], fill=(180, 185, 220, 255), width=6)

    # Arco de suporte do mic
    arc_w = 230
    draw.arc([cx - arc_w//2, cy - 20, cx + arc_w//2, cy + 190], start=0, end=180, fill=(255, 255, 255, 255), width=24)

    # Haste e base do mic
    draw.line([cx, cy + 190, cx, cy + 280], fill=(255, 255, 255, 255), width=24)
    draw.rounded_rectangle([cx - 90, cy + 280, cx + 90, cy + 304], radius=12, fill=(255, 255, 255, 255))

    # 3. Ondas sonoras de voz radiantes nas laterais (estilo Superwhisper/Siri)
    wave_color_1 = (129, 140, 248, 230)
    wave_color_2 = (192, 132, 252, 200)

    # Esquerda
    draw.arc([cx - 320, cy - 100, cx - 180, cy + 180], start=110, end=250, fill=wave_color_1, width=18)
    draw.arc([cx - 400, cy - 150, cx - 220, cy + 230], start=115, end=245, fill=wave_color_2, width=14)

    # Direita
    draw.arc([cx + 180, cy - 100, cx + 320, cy + 180], start=-70, end=70, fill=wave_color_1, width=18)
    draw.arc([cx + 220, cy - 150, cx + 400, cy + 230], start=-65, end=65, fill=wave_color_2, width=14)

    # 4. Gera todos os tamanhos canônicos do macOS iconset
    sizes = [
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

    for s, name in sizes:
        resized = img.resize((s, s), Image.Resampling.LANCZOS)
        resized.save(iconset_dir / name, "PNG")

    # 5. Converte para .icns usando a ferramenta oficial iconutil da Apple
    cmd = ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(output_icns_path)]
    subprocess.run(cmd, check=True)

    # Limpeza do iconset temporário
    for f in iconset_dir.glob("*.png"):
        f.unlink()
    iconset_dir.rmdir()
    print(f"[OK] AppIcon.icns gerado com sucesso em: {output_icns_path}")

if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "AppIcon.icns"
    generate_app_icon(out)
