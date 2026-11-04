#!/usr/bin/env python3
"""Genera un PDF desde una página de Moodle que requiere login (campusoversoft)."""
import re
import sys
from playwright.sync_api import sync_playwright, expect

LOGIN_URL = "https://www.campusoversoft.net/login/index.php"
TARGET_URL = "https://www.campusoversoft.net/mod/page/view.php?id=1535"
USERNAME = "vfranceschini@donnet.com.ar"
PASSWORD = "Vf040923*"
OUT_PDF = "/workspace/AD-0_Km_Unidad_4_Parte_1.pdf"
OUT_PNG = "/workspace/AD-0_Km_Unidad_4_Parte_1.png"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="es-AR",
        )
        page = ctx.new_page()

        # --- Login ---
        print("[1/4] Abriendo página de login...")
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        page.fill('input[name="username"]', USERNAME)
        page.fill('input[name="password"]', PASSWORD)
        page.click('button[type="submit"], input[type="submit"]')
        page.wait_for_load_state("networkidle", timeout=60000)

        if "login" in page.url or page.locator('input[name="password"]').count() > 0:
            err = page.locator(".alert, .loginerrors").inner_text() if page.locator(".loginerrors").count() else ""
            print(f"ERROR: El login falló. URL actual: {page.url}\n{err}")
            sys.exit(2)
        print(f"[2/4] Login OK -> {page.url}")

        # --- Ir a la página objetivo ---
        print(f"[3/4] Navegando a {TARGET_URL} ...")
        page.goto(TARGET_URL, wait_until="networkidle", timeout=90000)
        title = page.title()
        print(f"Título: {title}")

        # Esperar a que cargue el iframe del video (Vimeo) para que se renderice
        try:
            frame = page.frame_locator('iframe[src*="player.vimeo.com"]')
            frame.locator("*").first.wait_for(timeout=20000)
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f"(aviso) iframe de video no detectado: {e}")

        # --- Extraer título y cuerpo real de la página Moodle ---
        # El video está en Vimeo con privacidad restringida (no se puede descargar ni
        # embeber fuera del campus). Se reemplaza el iframe por su póster oficial,
        # capturando la imagen dentro de la sesión ya autenticada.
        poster_b64 = None
        try:
            vid_resp = page.evaluate(
                """async () => {
                    const f = document.querySelector('iframe[src*="vimeo"]');
                    if (!f) return null;
                    const id = f.src.match(/video\\/(\\d+)/)[1];
                    for (const url of [`https://i.vimeocdn.com/video/${id}_1280x720.jpg`,
                                       `https://vumbnail.com/${id}.jpg`]) {
                        try {
                            const r = await fetch(url);
                            if (!r.ok) continue;
                            const buf = await r.arrayBuffer();
                            let bin = ''; const bytes = new Uint8Array(buf);
                            for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
                            return { url, b64: btoa(bin) };
                        } catch (e) {}
                    }
                    return null;
                }"""
            )
            if vid_resp:
                poster_b64 = vid_resp["b64"]
                print(f"Póster del video obtenido ({len(poster_b64)} chars base64)")
        except Exception as e:
            print(f"(aviso) no se pudo obtener el póster: {e}")

        page.evaluate(
            """() => {
                const f = document.querySelector('iframe[src*="vimeo"]');
                if (!f) return;
                const wrap = document.createElement('div');
                const m = f.src.match(/video\\/(\\d+)/);
                const img = document.createElement('img');
                img.style.width = '640px'; img.style.maxWidth = '100%';
                img.src = m ? `https://i.vimeocdn.com/video/${m[1]}_1280x720.jpg` : '';
                const cap = document.createElement('div');
                cap.textContent = '🎬 Video de la clase — ver online: ' + f.src;
                cap.style.cssText = 'font-size:12px;color:#555;margin-top:6px;word-break:break-all;';
                wrap.append(img, cap);
                f.replaceWith(wrap);
            }"""
        )
        page.wait_for_timeout(2000)

        info = page.evaluate(
            """() => {
                const h1 = document.querySelector('h1.page-header-headings, .activity-header h1, h1');
                const main = document.querySelector('[role="main"]') ||
                             document.querySelector('#region-main');
                return {
                    title: h1 ? h1.innerText.trim() : document.title,
                    bodyHTML: main ? main.innerHTML : '',
                    videoURL: (()=>{const f=document.querySelector('iframe');return f?f.src:''})()
                };
            }"""
        )
        print(f"Contenido extraído: '{info['title']}', {len(info['bodyHTML'])} chars de HTML")

        # --- Captura PNG completa (respeta videos/iframes renderizados) ---
        page.screenshot(path=OUT_PNG, full_page=True)
        print(f"PNG guardado: {OUT_PNG}")

        # --- Construir documento limpio y generar el PDF ---
        body_html = info["bodyHTML"]
        if poster_b64 and "i.vimeocdn.com" in body_html:
            data_uri = f"data:image/jpeg;base64,{poster_b64}"
            body_html = re.sub(r'src="https://i\.vimeocdn\.com[^"]*"', f'src="{data_uri}"', body_html, count=1)

        clean_doc = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
        <style>
          body {{ font-family: Arial, Helvetica, sans-serif; color:#1d1d1f; margin:0; }}
          h1 {{ font-size:22px; border-bottom:2px solid #4a6fa5; padding-bottom:8px; }}
          .meta {{ color:#666; font-size:12px; margin-bottom:16px; }}
          iframe {{ width:640px; height:360px; max-width:100%; border:0; background:#000; }}
          img {{ max-width:100%; }}
        </style></head><body>
        <h1>{info['title']}</h1>
        <div class="meta">Fuente: {TARGET_URL} &nbsp;|&nbsp; Campus Oversoft</div>
        {body_html}
        </body></html>"""

        page.goto("about:blank")
        page.set_content(clean_doc, wait_until="networkidle")
        page.wait_for_timeout(2000)
        page.emulate_media(media="screen")
        page.pdf(
            path=OUT_PDF,
            format="A4",
            print_background=True,
            prefer_css_page_size=False,
            margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"},
        )
        print("PDF generado con el contenido limpio")

        print(f"[4/4] Listo -> {OUT_PDF}")
        browser.close()


if __name__ == "__main__":
    main()
