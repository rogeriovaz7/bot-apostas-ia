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
    """Busca os jogos de futebol de todos os campeonatos disponíveis na The Odds API"""
    # Usamos o desporto geral 'soccer' para abranger todas as ligas mundiais
    url = f"https://api.the-odds-api.com/v4/sports/soccer/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url)
            data = response.json()
            if isinstance(data, list):
                return data if len(data) > 0 else []
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
    end except Exception as e:
    except Exception as e:
        print(f"❌ Erro ao gerar análise com o Gemini: {e}")
        return "Desculpe, ocorreu um erro ao gerar a análise neste momento."

# ==========================================
# COMANDO INTERATIVO GLOBAL: /analise
# ==========================================
async def cmd_analise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executado quando o utilizador envia /analise [Equipa] no Telegram"""
    try:
        termo_pesquisa = " ".join(context.args).strip().lower()
        
        mensagem_status = await update.message.reply_text("🔍 A varrer todos os campeonatos mundiais na API de odds...")
        
        jogos = await buscar_odds_futebol()
        if not jogos:
            await mensagem_status.edit_text("⚠️ De momento não foram encontrados jogos ativos em nenhum campeonato.")
            return

        jogo_selecionado = None

        if termo_pesquisa:
            # Procura o termo em qualquer jogo de qualquer liga do mundo
            for jogo in jogos:
                home = jogo.get("home_team", "").lower()
                away = jogo.get("away_team", "").lower()
                if termo_pesquisa in home or termo_pesquisa in away:
                    jogo_selecionado = jogo
                    break
            
            if not jogo_selecionado:
                await mensagem_status.edit_text(
                    f"⚠️ Não encontrei nenhum jogo ativo para **'{termo_pesquisa}'** em nenhum campeonato global.\n\n"
                    f"Nota: Apenas aparecem jogos que tenham cotações ativas nas casas de apostas no momento."
                , parse_mode='Markdown')
                return
        else:
            # Se não escrever nada, pega no primeiro jogo global disponível
            jogo_selecionado = jogos[0]

        # Executa a geração da IA em segundo plano
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
    print("🤖 A configurar ligação ao Telegram com campeonatos globais...")
    
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
        
    print("✅ Bot online a monitorizar todas as ligas de futebol do mundo!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
