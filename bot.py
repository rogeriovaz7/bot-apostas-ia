import os
import time
import asyncio
import unicodedata
import httpx
from difflib import SequenceMatcher
from google import genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

# Carrega as chaves secretas do ficheiro .env ou variáveis de ambiente
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

# Validação das variáveis essenciais
if not all([TELEGRAM_TOKEN, GEMINI_API_KEY, ODDS_API_KEY]):
    print("⚠️ ERRO: Alguma chave essencial (TELEGRAM_TOKEN, GEMINI_API_KEY ou ODDS_API_KEY) está em falta!")
    exit(1)

# Inicializar o cliente oficial do Google Gemini (google-genai SDK)
client_gemini = genai.Client(api_key=GEMINI_API_KEY)

# Dicionário de sinónimos/apelidos para clubes conhecidos
ALIAS_EQUIPAS = {
    "vitoria sc": "guimaraes",
    "vitoria sport clube": "guimaraes",
    "vsc": "guimaraes",
    "sporting cp": "sporting lisbon",
    "slb": "benfica",
    "sl benfica": "benfica",
    "fcp": "porto",
    "fc porto": "porto",
    "braga": "sc braga",
    "vitoria fc": "setubal"
}

def remover_acentos(texto: str) -> str:
    """Remove acentos e converte o texto para minúsculas para padronizar pesquisas."""
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    ).lower()

def limpar_termos_ruido(texto: str) -> str:
    """Remove palavras de suporte e abreviaturas comuns que interferem na pesquisa."""
    palavras_ignorar = {"sc", "fc", "cf", "cd", "ud", "sport", "clube", "de", "do", "da", "e"}
    palavras = remover_acentos(texto).split()
    filtradas = [p for p in palavras if p not in palavras_ignorar]
    return " ".join(filtradas) if filtradas else remover_acentos(texto)

def calcular_similaridade(a: str, b: str) -> float:
    """Retorna um valor entre 0.0 e 1.0 indicando a semelhança entre dois textos (Fuzzy Ratio)."""
    return SequenceMatcher(None, a, b).ratio()

async def buscar_odds_futebol():
    """Busca cotações em várias ligas principais (h2h + totals) via The Odds API."""
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
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list) and len(data) > 0:
                        todos_os_jogos.extend(data)
            except Exception as e:
                print(f"⚠️ Erro ao buscar liga {liga}: {e}")
                
    return todos_os_jogos

def gerar_analise_gemini(dados_jogo):
    """Pede ao Gemini para analisar o jogo com resiliência a erros temporários 503."""
    prompt = f"""
    Atue como um analista sénior de apostas desportivas especializado em valor matemático (+EV).
    Analise os seguintes dados do jogo de futebol, que incluem cotações para o resultado final (1X2) e o mercado de golos (Mais/Menos):
    {dados_jogo}
    
    Selecione o mercado com **melhor valor esperado positivo (+EV)**, que pode ser o Vencedor (1X2) ou o mercado de Golos (ex: Mais/Menos de 2.5 Golos). Formate a resposta rigorosamente em Markdown para o Telegram com esta estrutura exata:
    
    ⚽ **JOGO:** [Equipa A vs Equipa B]
    📊 **MERCADO RECOMENDADO:** [Ex: Vitória Equipa A / Mais de 2.5 Golos]
    📈 **ODD MÍNIMA SUGERIDA:** [Ex: 1.85]
    💡 **JUSTIFICATIVA MATEMÁTICA:** [ExplIQUE em 2 frases curtas o porquê do valor]
    ⚠️ **GESTÃO DE RISCO:** [Recomendação de Stake, ex: 1 Unidade / 1% da banca]
    """
    
    # Sistema de Retentativas em caso de instabilidade ou pico de carga (Error 503)
    max_tentativas = 3
    for tentativa in range(1, max_tentativas + 1):
        try:
            response = client_gemini.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            if response and response.text:
                return response.text
        except Exception as e:
            print(f"⚠️ Tentativa {tentativa}/{max_tentativas} da IA falhou: {e}")
            if tentativa < max_tentativas:
                time.sleep(2)
            else:
                return "❌ Os servidores da IA estão temporariamente sobrecarregados. Por favor, tente novamente em alguns instantes."

    return "❌ Não foi possível gerar a análise matemática neste momento."

# ==========================================
# COMANDO INTERATIVO COM ASSOCIAÇÃO INTELIGENTE
# ==========================================
async def cmd_analise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executado quando o utilizador envia /analise [Equipa] no Telegram."""
    mensagem_status = None
    try:
        termo_bruto = " ".join(context.args).strip()
        termo_normalizado = remover_acentos(termo_bruto)
        
        # 1. Aplica mapeamento direto de alias se existir (ex: "fc porto" -> "porto")
        termo_pesquisa = ALIAS_EQUIPAS.get(termo_normalizado, termo_normalizado)
        termo_limpo = limpar_termos_ruido(termo_pesquisa)
        
        mensagem_status = await update.message.reply_text("🔍 A consultar os jogos disponíveis e a associar a equipa...")
        
        jogos = await buscar_odds_futebol()
        if not jogos:
            await mensagem_status.edit_text("⚠️ De momento não foram encontrados jogos ativos nas ligas monitorizadas.")
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
                
                # A) Correspondência exata por palavra no nome
                if termo_pesquisa in home_norm or termo_pesquisa in away_norm:
                    jogo_selecionado = jogo
                    break
                
                # B) Correspondência exata do termo limpo de ruído
                if termo_limpo in home_clean or termo_limpo in away_clean:
                    jogo_selecionado = jogo
                    break

                # C) Fuzzy Matching com limiar de confiança seguro (>= 0.55)
                sim_home = max(calcular_similaridade(termo_pesquisa, home_norm), calcular_similaridade(termo_limpo, home_clean))
                sim_away = max(calcular_similaridade(termo_pesquisa, away_norm), calcular_similaridade(termo_limpo, away_clean))
                maior_sim = max(sim_home, sim_away)

                if maior_sim > melhor_pontuacao and maior_sim >= 0.55:
                    melhor_pontuacao = maior_sim
                    jogo_selecionado = jogo

            if not jogo_selecionado:
                await mensagem_status.edit_text(
                    f"⚠️ Não foi possível associar **'{termo_bruto}'** a nenhum jogo ativo com cotações abertas de momento.\n\n"
                    f"💡 **Dica:** Tente pesquisar por uma parte mais simples do nome (ex: `/analise porto` ou `/analise guimaraes`)."
                , parse_mode='Markdown')
                return
        else:
            jogo_selecionado = jogos[0]

        await mensagem_status.edit_text("🤖 A calcular valor matemático (+EV) com o Gemini...")
        
        # Execução assíncrona da IA com tempo limite de segurança
        analise = await asyncio.wait_for(
            asyncio.to_thread(gerar_analise_gemini, jogo_selecionado),
            timeout=30.0
        )
        
        await mensagem_status.edit_text(analise, parse_mode='Markdown')

    except asyncio.TimeoutError:
        print("❌ Timeout na resposta do Gemini.")
        if mensagem_status:
            await mensagem_status.edit_text("⚠️ A análise demorou demasiado tempo a responder. Por favor, tente novamente.")
    except Exception as e:
        print(f"❌ Erro no comando /analise: {e}")
        if mensagem_status:
            try:
                await mensagem_status.edit_text("❌ Ocorreu um erro ao processar a sua solicitação.")
            except Exception:
                pass

def main():
    """Inicia o Bot do Telegram com tratamento do Event Loop."""
    print("🤖 A iniciar o bot no Render com modelo estável e retentativas...")
    
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
        
    print("✅ Bot online e totalmente operacional!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
