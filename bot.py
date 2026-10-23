import os
import requests
from openai import OpenAI
from telegram import Bot
from dotenv import load_dotenv

# Carrega as chaves secretas do ficheiro .env
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

# Validação rápida para garantir que preencheu o .env
if not all([TELEGRAM_TOKEN, TELEGRAM_CHANNEL_ID, OPENAI_API_KEY, ODDS_API_KEY]):
    print("⚠️ ERRO: Alguma chave está em falta no ficheiro .env! Verifique se preencheu todos os campos.")
    exit(1)

# Inicializar clientes
client = OpenAI(api_key=OPENAI_API_KEY)
bot = Bot(token=TELEGRAM_TOKEN)

def buscar_odds_futebol():
    """Busca as odds de futebol da Premier League na The Odds API"""
    url = f"https://api.the-odds-api.com/v4/sports/soccer_epl/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h"
    try:
        response = requests.get(url)
        data = response.json()
        
        # Verifica se a API retornou uma lista válida de jogos
        if isinstance(data, list):
            return data[:2] if len(data) > 0 else []
        else:
            print(f"⚠️ Aviso da API de Odds: {data}")
            return []
    except Exception as e:
        print(f"❌ Erro ao buscar odds: {e}")
        return []

def gerar_analise_ia(dados_jogo):
    """Pede ao ChatGPT para analisar o jogo e encontrar valor matemático"""
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
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Erro ao gerar análise com a OpenAI: {e}")
        return None

def publicar_sinal_canal():
    print("🔍 A procurar jogos na API e a gerar análise com IA...")
    jogos = buscar_odds_futebol()
    
    if not jogos:
        print("⚠️ Nenhum jogo encontrado ou erro na API de odds. Tente novamente mais tarde.")
        return

    # Analisa o primeiro jogo da lista
    analise_pronta = gerar_analise_ia(jogos[0])
    
    if not analise_pronta:
        print("⚠️ A análise não pôde ser gerada.")
        return

    try:
        # Envia a mensagem gerada para o seu canal do Telegram
        bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=analise_pronta,
            parse_mode='Markdown'
        )
        print("✅ Sucesso! Sinal publicado no canal do Telegram.")
    except Exception as e:
        print(f"❌ Erro ao enviar mensagem para o Telegram: {e}")
        print("Dica: Certifique-se de que o bot é Administrador do canal do Telegram.")

if __name__ == "__main__":
    # Executa o teste imediato ao iniciar o script
    publicar_sinal_canal()