import os
import asyncio
import unicodedata
import httpx
from difflib import SequenceMatcher
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

def remover_acentos(texto):
    """Remove acentos e converte para minúsculas para facilitar a comparação"""
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    ).lower()

def limpar_termos_ruido(texto):
    """Remove palavras de suporte/abreviaturas comuns que atrapalham a pesquisa"""
    palavras_ignorar = {"sc", "fc", "cf", "cd", "ud", "sport", "clube", "de", "do", "da", "e"}
    palavras = remover_acentos(texto).split()
    filtradas = [p for p in palavras if p not in palavras_ignorar]
    return " ".join(filtradas) if filtradas else remover_acentos(texto)

def calcular_similaridade(a, b):
    """Retorna um valor de 0.0 a 1.0 indicando o quão parecidos dois textos são"""
    return SequenceMatcher(None, a, b).ratio()

async def buscar_odds_futebol():
    """Busca odds em várias ligas incluindo múltiplos mercados (1X2 e Totais/Golos)"""
    ligas = [
        "soccer_portugal_primeira_liga",
        "soccer_epl",
        "soccer_spain_la_liga",
        "soccer_italy_serie_a",
        "soccer_uefa_champions_league"
    ]
    
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
# COMANDO INTERATIVO COM ASSOCIAÇÃO INTELIGENTE
# ==========================================
async def cmd_analise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executado quando o utilizador envia /analise [Equipa] no Telegram"""
    try:
        termo_bruto = " ".join(context.args).strip()
        termo_limpo = limpar_termos_ruido(termo_bruto)
        termo_normalizado = remover_acentos(termo_bruto)
        
        mensagem_status = await update.message.reply_text("🔍 A consultar os jogos disponíveis e a associar a equipa...")
        
        jogos = await buscar_odds_futebol()
        if not jogos:
            await mensagem_status.edit_text("⚠️ De momento não foram encontrados jogos ativos.")
            return

        jogo_selecionado = None

        if termo_bruto:
            melhor_pontuacao = 0.0
            
            for jogo in jogos:
                home_raw = jogo.get("home_team", "")
                away_raw = jogo.get("away_team", "")
                
                home_norm = remover_acentos(home_raw)
                away_norm = remover_acentos(away_raw)
                
                home_clean = limpar_termos_ruido(home_raw)
                away_clean = limpar_termos_ruido(away_raw)
                
                # 1. Pesquisa direta da palavra limpa principal (ex: "vitoria" em "vitoria guimaraes")
                if termo_limpo in home_clean or termo_limpo in away_clean:
                    jogo_selecionado = jogo
                    break
                
                # 2. Pesquisa de sub-string no nome completo
                if termo_normalizado in home_norm or termo_normalizado in away_norm:
                    jogo_selecionado = jogo
                    break

                # 3. Fuzzy matching no nome limpo de ruídos
                sim_home = calcular_similaridade(termo_limpo, home_clean)
                sim_away = calcular_similaridade(termo_limpo, away_clean)
                maior_sim = max(sim_home, sim_away)

                if maior_sim > melhor_pontuacao and maior_sim > 0.25:
                    melhor_pontuacao = maior_sim
                    jogo_selecionado = jogo

            if not jogo_selecionado:
                await mensagem_status.edit_text(
                    f"⚠️ Não foi possível associar **'{termo_bruto}'** a nenhum jogo ativo de momento.\n\n"
                    f"💡 **Dica:** Tente pesquisar por uma parte mais simples do nome (ex: `/analise guimaraes` ou `/analise vitoria`)."
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
    print("🤖 A configurar ligação ao Telegram com filtro inteligente de equipas...")
    
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
        
    print("✅ Bot online a escutar comandos!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
