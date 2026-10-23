import os
import asyncio
import httpx
from google import genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

# Carrega as chaves secretas
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

# Validação rápida
if not all([TELEGRAM_TOKEN, GEMINI_API_KEY, ODDS_API_KEY]):
    print("⚠️ ERRO: Alguma chave essencial está em falta!")
    exit(1)

# Inicializar o cliente do Google Gemini
client_gemini = genai.Client(api_key=GEMINI_API_KEY)

async def buscar_odds_futebol():
    """Busca odds em várias ligas e agora incluindo múltiplos mercados (1X2 e Totais/Golos)"""
    ligas = [
        "soccer_portugal_primeira_liga",
        "soccer_epl",
        "soccer_spain_la_liga",
        "soccer_italy_serie_a",
        "soccer_uefa_champions_league"
    ]
    
    # Adicionamos 'totals' (Mais/Menos Golos) ao parâmetro markets
    markets = "h2h,totals"
    
    todos_os_jogos = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for liga in ligas:
            url = f"https://api.the-odds-api.com/v4/sports/{liga}/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets={markets}"
            try:
                response = await client.get(url)
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    todos_os_jogos.extend(data)
            except Exception as e:
                print(f"⚠️ Erro ao buscar liga {liga}: {e}")
                
    return todos_os_jogos

def gerar_analise_gemini(dados_jogo):
    """Pede ao Gemini para analisar o jogo e encontrar valor matemático (+EV) em qualquer mercado"""
    prompt = f"""
    Atue como um analista sénior de apostas desportivas especializado em valor matemático (+EV).
    Analise os seguintes dados do jogo de futebol, que incluem cotações para o resultado final (1X2) e o mercado de golos (Mais/Menos):
    {dados_jogo}
    
    Selecione o mercado com **melhor valor esperado positivo (+EV)**, que pode ser o Vencedor (1X2) ou o mercado de Golos (ex: Mais/Menos de 2.5 Golos). Formate a resposta rigorosamente em Markdown para o Telegram com esta estrutura exata:
    
    ⚽ **JOGO:** [Equipa A vs Equipa B]
    📊 **MERCADO RECOMENDADO:** [Ex: Vitória Equipa A / Mais de 2.5 Golos]
    📈 **ODD MÍNIMA SUGERIDA:** [Ex: 1.85]
    💡 **JUSTIFICATIVA MATEMÁTICA:** [Explique em 2 frases curtas o porquê do valor]
    ⚠️ **GESTÃO DE RISCO:** [Recomendação de Stake, ex: 1 Unidade / 1% da banca]
    """
    try:
        response = client_gemini.models.generate_content(
            model='gemini-3.8-flash',
            contents=prompt,
        )
        return response.text
    except Exception as e:
        print(f"❌ Erro ao gerar análise com o Gemini: {e}")
        return "Desculpe, ocorreu um erro ao gerar a análise neste momento."

# ==========================================
# COMANDO INTERATIVO: /analise
# ==========================================
async def cmd_analise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executado quando o utilizador envia /analise [Equipa] no Telegram"""
    try:
        termo_pesquisa = " ".join(context.args).strip().lower()
        
        mensagem_status = await update.message.reply_text("🔍 A consultar múltiplos mercados de odds e a pedir análise ao Gemini...")
        
        jogos = await buscar_odds_futebol()
        if not jogos:
            await mensagem_status.edit_text("⚠️ De momento não foram encontrados jogos ativos.")
            return

        jogo_selecionado = None

        if termo_pesquisa:
            for jogo in jogos:
                home = jogo.get("home_team", "").lower()
                away = jogo.get("away_team", "").lower()
                if termo_pesquisa in home or termo_pesquisa in away:
                    jogo_selecionado = jogo
                    break
            
            if not jogo_selecionado:
                await mensagem_status.edit_text(
                    f"⚠️ Não encontrei nenhum jogo ativo para **'{termo_pesquisa}'**."
                , parse_mode='Markdown')
                return
        else:
            jogo_selecionado = jogos[0]

        analise = await asyncio.to_thread(gerar_analise_gemini, jogo_selecionado)
        
        await mensagem_status.edit_text(analise, parse_mode='Markdown')
    except Exception as e:
        print(f"❌ Erro no comando /analise: {e}")
        try:
            await mensagem_status.edit_text("❌ Ocorreu um erro ao processar a sua solicitação.")
        except:
            pass

def main():
    """Inicia o Bot do Telegram"""
    print("🤖 A configurar ligação ao Telegram com múltiplos mercados...")
    
    application = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .build()
    )
    
    application.add_handler(CommandHandler("analise", cmd_analise))
    
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    print("✅ Bot online com suporte a mercados de golos e resultado!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
