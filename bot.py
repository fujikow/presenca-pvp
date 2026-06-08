import discord
from discord.ext import commands
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import os
from dotenv import load_dotenv

# --- CARREGAR VARIÁVEIS DE AMBIENTE (Segurança) ---
load_dotenv()

# --- CONFIGURAÇÕES FIXAS ---
# Substitua o número abaixo pelo ID real do canal de PvP do seu servidor
ID_CANAL_PVP = 1513669911782883528 

# --- INICIALIZAÇÃO DO FIREBASE ---
# O Render lerá o arquivo 'firebase-key.json' que você vai criar em "Secret Files"
cred = credentials.Certificate('firebase-key.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

# --- CONFIGURAÇÃO DO BOT ---
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Dicionário de 16 horários e reações (Letras A até P)
HORARIOS = {
    "🇦": "08:00 - 09:00", "🇧": "09:00 - 10:00", "🇨": "10:00 - 11:00",
    "🇩": "11:00 - 12:00", "🇪": "12:00 - 13:00", "🇫": "13:00 - 14:00",
    "🇬": "14:00 - 15:00", "🇭": "15:00 - 16:00", "🇮": "16:00 - 17:00",
    "🇯": "17:00 - 18:00", "🇰": "18:00 - 19:00", "🇱": "19:00 - 20:00",
    "🇲": "20:00 - 21:00", "🇳": "21:00 - 22:00", "🇴": "22:00 - 23:00",
    "🇵": "23:00 - 23:59"
}

@bot.event
async def on_ready():
    print(f'Bot logado com sucesso como {bot.user}')

# --- COMANDO PRINCIPAL: GERAR CARD ---
@bot.command()
async def pvp(ctx):
    canal = bot.get_channel(ID_CANAL_PVP)
    if not canal:
        await ctx.send("Erro: Não encontrei o canal configurado. Verifique o ID no código.")
        return

    # Pega a data de hoje formatada
    data_hoje = datetime.now().strftime('%d/%m/%Y')

    embed = discord.Embed(
        title=f"⚔️ PRESENÇA PVP MEGAMU - {data_hoje}",
        description="Clique nas reações abaixo para marcar os horários que você jogará hoje.",
        color=0x005CA9 
    )
    
    for emoji, horario in HORARIOS.items():
        embed.add_field(name=f"{emoji} {horario}", value="Nenhum jogador", inline=True)
    
    embed.set_footer(text=f"Lista gerada em: {data_hoje} | Gestão MEGAMU")
    
    mensagem = await canal.send(embed=embed)
    
    # Se o comando for digitado em outro canal, avisa o líder que deu certo
    if ctx.channel.id != ID_CANAL_PVP:
        await ctx.send(f"✅ Card de presença gerado com sucesso no canal {canal.mention}!")

    # Adiciona todas as reações à mensagem nova
    for emoji in HORARIOS.keys():
        await mensagem.add_reaction(emoji)

    # Armazena os dados do card ativo no Firebase para o bot saber quem monitorar
    db.collection('config').document('mensagem_ativa').set({
        'mensagem_id': str(mensagem.id),
        'canal_id': str(canal.id),
        'data_evento': data_hoje
    })

# --- EVENTOS: ADICIONAR E REMOVER REAÇÃO ---
@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id: return # Ignora cliques do próprio bot
    await processar_reacao(payload, adicionar=True)

@bot.event
async def on_raw_reaction_remove(payload):
    await processar_reacao(payload, adicionar=False)

async def processar_reacao(payload, adicionar):
    # Confere se a mensagem clicada é o Card de PvP ativo
    doc_ref = db.collection('config').document('mensagem_ativa').get()
    if not doc_ref.exists or doc_ref.to_dict().get('mensagem_id') != str(payload.message_id):
        return

    emoji_usado = str(payload.emoji)
    if emoji_usado not in HORARIOS: return

    dados_config = doc_ref.to_dict()
    horario_selecionado = HORARIOS[emoji_usado]
    data_evento = dados_config.get('data_evento', 'Sem Data')
    
    canal = bot.get_channel(payload.channel_id)
    mensagem = await canal.fetch_message(payload.message_id)
    membro = bot.get_user(payload.user_id) or await bot.fetch_user(payload.user_id)
    
    # --- LÓGICA DE BANCO DE DADOS ---
    presenca_ref = db.collection('presencas_pvp').document(data_evento.replace('/', '-')).collection('slots').document(horario_selecionado)
    doc = presenca_ref.get()
    
    jogadores = doc.to_dict().get('jogadores', []) if doc.exists else []

    if adicionar and membro.display_name not in jogadores:
        jogadores.append(membro.display_name)
    elif not adicionar and membro.display_name in jogadores:
        jogadores.remove(membro.display_name)
        
    presenca_ref.set({'jogadores': jogadores})

    # --- ATUALIZAÇÃO DO CARD NO DISCORD ---
    embed = mensagem.embeds[0]
    novo_embed = discord.Embed(title=embed.title, description=embed.description, color=embed.color)
    novo_embed.set_footer(text=embed.footer.text)

    # Reconstrói a lista refazendo todos os campos
    for index, (emoji, horario) in enumerate(HORARIOS.items()):
        if horario == horario_selecionado:
            texto_jogadores = "\n".join(jogadores) if jogadores else "Nenhum jogador"
            novo_embed.add_field(name=f"{emoji} {horario}", value=texto_jogadores, inline=True)
        else:
            novo_embed.add_field(name=embed.fields[index].name, value=embed.fields[index].value, inline=True)

    await mensagem.edit(embed=novo_embed)

# --- EXECUÇÃO DO BOT ---
# O Token é puxado do arquivo .env ou das Variáveis de Ambiente do Render
TOKEN = os.getenv('DISCORD_TOKEN')
bot.run(TOKEN)