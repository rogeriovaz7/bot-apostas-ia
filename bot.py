import os
import asyncio
import requests
from google import genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

# Carrega as chaves secretas (caso esteja a testar localmente no PC com o ficheiro .env)
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

# Validação rápida para garantir que todas as chaves essenciais estão presentes
if not all([TELEGRAM_TOKEN, GEMINI_API_KEY, ODDS_API_KEY]):
    print("⚠️ ERRO: Alguma chave essencial está em falta! Verifique as Variáveis de Ambiente ou o .env.")
    exit(1)

# Inicializar o cliente do Google Gemini
client_gemini = genai.Client(api_key=GEMINI_API_KEY)

def buscar_odds_futebol():
    """Busca as odds de futebol da Premier League na The Odds API"""
    url = f"https://api.the-odds-api.com/v4/sports/soccer_epl/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h"
    try:
        response = requests.get(url)
        data = response.json()
        if isinstance(data, list):
            return data[:3] if len(data) > 0 else []
        return []
    except Exception as e:
        print(f"❌ Erro ao buscar odds: {e}")
        return []

def gerar_analise_gemini(dados_jogo):
    """Pede ao Gemini para analisar o jogo e encontrar valor matemático (+EV)"""
    prompt = f"""
    Atue como um analista sénior de apostas desportivas especializado em valor matemático (+EV).
    Analise os seguintes dados do jogo de futebol e respetivas odds de mercado:
    {dados_jogo}
    
    Identifique se existe alguma oportunidade com valor esperado positivo. Formate a resposta rigorosamente em Markdown para o Telegram com esta estrutura exata:
    
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
    """Executado quando o utilizador envia /analise no Telegram"""
    chat_id = update.effective_chat.id
    
    # Envia uma mensagem inicial a avisar que está a processar
    mensagem_status = await update.message.reply_text("🔍 A consultar o mercado de odds e a pedir análise ao Gemini...")
    
    jogos = buscar_odds_futebol()
    if not jogos:
        await mensagem_status.edit_text("⚠️ De momento não foram encontrados jogos disponíveis na API de odds.")
        return

    # Analisa o primeiro jogo disponível da lista
    analise = gerar_analise_gemini(jogos[0])
    
    # Edita a mensagem com o resultado final da análise
    await mensagem_status.edit_text(analise, parse_mode='Markdown')

def main():
    """Inicia o Bot do Telegram com suporte a loop de eventos compatível"""
    print("🤖 Bot interativo do Telegram iniciado e a configurar aplicação...")
    
    # Constrói a aplicação do bot
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Regista o comando /analise
    application.add_handler(CommandHandler("analise", cmd_analise))
    
    # Configuração segura do loop de eventos para evitar erros de Runtime
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    print("✅ Bot a escutar comandos em tempo real...")
    application.run_polling()

if __name__ == "__main__":
    main()
