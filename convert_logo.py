from svglib.svglib import svg2rlg
from reportlab.graphics import renderPM
from PIL import Image

# Read SVG and convert to ReportLab drawing
drawing = svg2rlg("AlyxDesktop/Assets/logo.svg")

# Render to PNG
renderPM.drawToFile(drawing, "AlyxDesktop/Assets/logo.png", fmt="PNG")

# Convert PNG to ICO
img = Image.open("AlyxDesktop/Assets/logo.png")
img.save("AlyxDesktop/Assets/logo.ico")
