
import os
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

def audit_chart_with_gemini_vision(chart_base64: str, pivot_text: str, ticker: str, timeframe: str, sma_context: str, analysis_id: str, system_prompt: str, mtf_charts: dict = None) -> str:
    """
    Perform Chart Audit using Google Gemini 1.5 Flash (Vision).
    Outputs HTML directly with Mometic/Trading Journal style design.
    """
    
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    
    if not api_key:
        return """
        <div style='background:#3d1418; padding:20px; border-radius:8px; border:1px solid #f85149; color:#E6EDF3'>
            <h3 style='color:#f85149; margin-top:0'>⚠️ Google AI Not Configured</h3>
            <p>Please add your Google Gemini API Key to Streamlit secrets:</p>
            <code style='background:#0d1117; padding:4px 8px; border-radius:4px'>GOOGLE_API_KEY = "your-key"</code>
        </div>
        """
        
    try:
        genai.configure(api_key=api_key)
        # Use Gemini Flash Latest - Stable alias
        model = genai.GenerativeModel('gemini-flash-latest')
        
        content_parts = []
        
        # Helper for images
        def get_image_part(b64):
            return {'mime_type': 'image/png', 'data': b64}

        # SYSTEM PROMPT
        content_parts.append(system_prompt)
        content_parts.append("\n\nSTRICT RULE: Focus on RISK assessment first. Be critical. DO NOT HALLUCINATE.")
        
        if mtf_charts and all(k in mtf_charts for k in ['monthly', 'weekly', 'daily', 'h4']):
            # MTF Mode
            content_parts.append(f"""
=== MULTI-TIMEFRAME TOP-DOWN ANALYSIS FOR {ticker} ===
{sma_context}

Analyse the following 4 charts in strict top-down order (Monthly -> Weekly -> Daily -> 4H).
Identify the Wave Count and Structure on each.
""")
            content_parts.append("**CHART 1: MONTHLY (Primary)**")
            content_parts.append(get_image_part(mtf_charts['monthly']))
            content_parts.append("**CHART 2: WEEKLY (Intermediate)**")
            content_parts.append(get_image_part(mtf_charts['weekly']))
            content_parts.append("**CHART 3: DAILY (Minor)**")
            content_parts.append(get_image_part(mtf_charts['daily']))
            content_parts.append("**CHART 4: 4-HOUR (Minuette)**")
            content_parts.append(get_image_part(mtf_charts['h4']))
        else:
            # Single Chart Mode
            content_parts.append(f"=== ANALYSIS FOR {ticker} ({timeframe}) ===\n{sma_context}")
            content_parts.append(get_image_part(chart_base64))
            
        content_parts.append(f"Pivot Data:\n{pivot_text}")
        content_parts.append("""
Please provide a Professional Elliott Wave & Risk Audit.

OUTPUT FORMAT:
Do not use Markdown code blocks. Just smooth text with formatting.

STRUCTURE:
1. EXECUTIVE SUMMARY (2-3 sentences max)
2. WAVE STRUCTURE (Breakdown by timeframe)
3. WEINSTEIN STAGE (Based on SMA)
4. KEY RISK LEVELS (Invalidation points)
5. FINAL VERDICT (Start line with "VERDICT: PASS" or "VERDICT: FAIL")
""")
        
        # Call Gemini
        response = model.generate_content(
            content_parts,
            generation_config=genai.types.GenerationConfig(
                temperature=0.2,
                max_output_tokens=2000,
            ),
            safety_settings={
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }
        )
        
        ai_text = response.text
        
        # HTML Styling (Dark Mode / Mometic Style)
        
        # Process text for HTML display
        formatted_text = ai_text.replace('\n', '<br>')
        formatted_text = formatted_text.replace('**', '<b>').replace('Executive Summary', '<span style="color:#F2CC60; font-weight:bold; font-size:1.1em">Executive Summary</span>')
        formatted_text = formatted_text.replace('VERDICT: PASS', '<span style="background:rgba(63, 185, 80, 0.2); color:#3FB950; padding:4px 8px; border-radius:4px; font-weight:bold; border:1px solid #3FB950">VERDICT: PASS</span>')
        formatted_text = formatted_text.replace('VERDICT: FAIL', '<span style="background:rgba(248, 81, 73, 0.2); color:#F85149; padding:4px 8px; border-radius:4px; font-weight:bold; border:1px solid #F85149">VERDICT: FAIL</span>')
        
        result_html = f"""
        <div style="background-color: #0D1117; border: 1px solid #30363D; border-radius: 8px; padding: 25px; color: #E6EDF3; font-family: 'Inter', system-ui, sans-serif;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; border-bottom: 1px solid #30363D; padding-bottom: 15px;">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 1.5em;">⚡</span>
                    <h3 style="margin: 0; color: #58A6FF; font-weight: 600;">AI Chart Audit</h3>
                </div>
                <div style="display:flex; gap:10px; align-items:center">
                    <span style="background-color: #238636; color: white; padding: 2px 8px; border-radius: 12px; font-size: 0.75em; font-weight: 600;">PRO</span>
                    <span style="background-color: #1F6FEB; color: white; padding: 4px 12px; border-radius: 12px; font-size: 0.85em; font-weight: 500;">Gemini Flash</span>
                </div>
            </div>
            
            <div style="font-size: 1.05em; line-height: 1.6; color: #C9D1D9;">
                {formatted_text}
            </div>
            
            <div style="margin-top: 25px; padding-top: 15px; border-top: 1px solid #21262D; font-size: 0.8em; color: #8B949E; display: flex; justify-content: space-between;">
                <span>ID: {analysis_id.split('_')[-1]} &bull; Generated: {analysis_id.split('_')[2]}:{analysis_id.split('_')[3]}</span>
                <span>Powered by Google Gemini Vision</span>
            </div>
        </div>
        """
        return result_html

    except Exception as e:
        import traceback
        return f"""
        <div style='background:#3d1418; padding:20px; border-radius:8px; border:1px solid #f85149; color:#E6EDF3'>
            <h3 style='color:#f85149; margin-top:0'>⚠️ AI Analysis Error</h3>
            <p>{str(e)}</p>
            <pre style='background:#0d1117; padding:10px; overflow:auto; font-size:0.8em'>{traceback.format_exc()}</pre>
        </div>
        """
