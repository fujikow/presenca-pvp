import discord
from discord.ext import commands, tasks
import firebase_admin
from firebase_admin import credentials, firestore
import datetime
import os
from dotenv import load_dotenv
import http.server
import socketserver
from threading import Thread

load_dotenv()

def iniciar_servidor_web():
    porta = int(os.environ.get('PORT', 8080))
    class MeuHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Servidor do Bot Online")
            
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", porta), MeuHandler) as httpd:
        httpd.serve_forever()

Thread(target=iniciar_servidor_web, daemon=True).start()

# --- CONFIGURAÇÕES FIXAS ---
ID_CANAL_PVP = 1513669911782883528 
ID_CARGO_BATTLE = 1487988014792708226 

FUSO_BR = datetime.timezone(datetime.timedelta(hours=-3))

cred = credentials.Certificate('firebase-key.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

HORARIOS = {
    "🇦": "00:00 - 02:00", "🇧": "02:00 - 04:00", "🇨": "04:00 - 06:00",
    "🇩": "06:00 - 08:00", "🇪": "08:00 - 10:00", "🇫": "10:00 - 12:00",
    "🇬": "12:00 - 14:00", "🇭": "14:00 - 16:00", "🇮": "16:00 - 18:00",
    "🇯": "18:00 - 20:00", "🇰": "20:00 - 22:00", "🇱": "22:00 - 00:00"
}

# --- FUNÇÃO DE SINCRONIZAÇÃO (ACORDA E ATUALIZA) ---
async def sincronizar_reacoes():
    print("Verificando se há perda de dados... Sincronizando Card ativo.")
    doc_ref = db.collection('config').document('mensagem_ativa').get()
    if not doc_ref.exists: return

    dados = doc_ref.to_dict()
    canal_id = int(dados.get('canal_id', 0))
    msg_id = int(dados.get('mensagem_id', 0))
    data_evento = dados.get('data_evento', 'Sem Data')

    canal = bot.get_channel(canal_id)
    if not canal: return

    try:
        mensagem = await canal.fetch_message(msg_id)
    except discord.NotFound:
        return 

    guild = mensagem.guild
    embed = mensagem.embeds[0]
    novo_embed = discord.Embed(title=embed.title, description=embed.description, color=embed.color)
    novo_embed.set_footer(text=embed.footer.text)

    for emoji_str, horario in HORARIOS.items():
        jogadores = []
        reacao = discord.utils.get(mensagem.reactions, emoji=emoji_str)
        
        if reacao:
            async for user in reacao.users():
                if user.id == bot.user.id: continue 
                membro = guild.get_member(user.id) or await guild.fetch_member(user.id)
                if membro:
                    jogadores.append(membro.display_name)
        
        presenca_ref = db.collection('presencas_pvp').document(data_evento.replace('/', '-')).collection('slots').document(horario)
        presenca_ref.set({'jogadores': jogadores})

        texto_jogadores = "\n".join(jogadores) if jogadores else "Nenhum jogador"
        novo_embed.add_field(name=f"{emoji_str} {horario} ({len(jogadores)})", value=texto_jogadores, inline=True)

    await mensagem.edit(content=mensagem.content, embed=novo_embed)
    print("Sincronização concluída com sucesso!")

# --- ROTINAS E EVENTOS ---
horario_reset = datetime.time(hour=0, minute=0, tzinfo=FUSO_BR)

@tasks.loop(time=horario_reset)
async def rotina_diaria_pvp():
    canal = bot.get_channel(ID_CANAL_PVP)
    if not canal: return

    try:
        doc_ref = db.collection('config').document('mensagem_ativa').get()
        if doc_ref.exists:
            msg_id = int(doc_ref.to_dict().get('mensagem_id'))
            msg_antiga = await canal.fetch_message(msg_id)
            await msg_antiga.delete()
    except Exception as e:
        print(f"Aviso ao limpar chat: {e}")

    data_hoje = datetime.datetime.now(FUSO_BR).strftime('%d/%m/%Y')

    # A cor já está ajustada aqui para o Azul do Grêmio (0x005CA9) que você utiliza
    embed = discord.Embed(
        title=f"⚔️ PRESENÇA PVP MEGAMU - {data_hoje}",
        description="Clique nas reações abaixo para marcar os horários que você jogará hoje.",
        color=0x005CA9 
    )
    
    for emoji, horario in HORARIOS.items():
        embed.add_field(name=f"{emoji} {horario} (0)", value="Nenhum jogador", inline=True)
    
    embed.set_footer(text=f"Lista gerada automaticamente | Gestão MEGAMU")
    
    mensagem_chamada = f"<@&{ID_CARGO_BATTLE}> **Lista atualizada! Marquem seus horários para o atropelo de hoje:**"
    nova_mensagem = await canal.send(content=mensagem_chamada, embed=embed)

    for emoji in HORARIOS.keys():
        await nova_mensagem.add_reaction(emoji)

    db.collection('config').document('mensagem_ativa').set({
        'mensagem_id': str(nova_mensagem.id),
        'canal_id': str(canal.id),
        'data_evento': data_hoje
    })

@bot.event
async def on_ready():
    print(f'Bot logado com sucesso como {bot.user}')
    
    # Executa a proteção contra perda de dados
    await sincronizar_reacoes()
    
    if not rotina_diaria_pvp.is_running():
        rotina_diaria_pvp.start()
        print("Rotina de reset diário ativada.")

@bot.command()
async def pvp(ctx):
    await rotina_diaria_pvp.coro()
    if ctx.channel.id != ID_CANAL_PVP:
        await ctx.send("✅ Card gerado manualmente com a marcação do cargo.")

# --- EVENTOS: ADICIONAR E REMOVER REAÇÃO ---
@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id: return
    await processar_reacao(payload)

@bot.event
async def on_raw_reaction_remove(payload):
    await processar_reacao(payload)

# Lógica unificada: Lê o Discord e escreve no Firebase (Espelho de segurança)
async def processar_reacao(payload):
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
    guild = bot.get_guild(payload.guild_id)
    
    jogadores = []
    reacao_real = discord.utils.get(mensagem.reactions, emoji=emoji_usado)
    
    if reacao_real:
        async for user in reacao_real.users():
            if user.id == bot.user.id: continue 
            membro = guild.get_member(user.id) or await guild.fetch_member(user.id)
            if membro:
                jogadores.append(membro.display_name)
    
    presenca_ref = db.collection('presencas_pvp').document(data_evento.replace('/', '-')).collection('slots').document(horario_selecionado)
    presenca_ref.set({'jogadores': jogadores})

    embed = mensagem.embeds[0]
    novo_embed = discord.Embed(title=embed.title, description=embed.description, color=embed.color)
    novo_embed.set_footer(text=embed.footer.text)

    for index, (emoji, horario) in enumerate(HORARIOS.items()):
        if horario == horario_selecionado:
            texto_jogadores = "\n".join(jogadores) if jogadores else "Nenhum jogador"
            novo_embed.add_field(name=f"{emoji} {horario} ({len(jogadores)})", value=texto_jogadores, inline=True)
        else:
            novo_embed.add_field(name=embed.fields[index].name, value=embed.fields[index].value, inline=True)

    await mensagem.edit(content=mensagem.content, embed=novo_embed)

# --- EXECUÇÃO ---
TOKEN = os.getenv('DISCORD_TOKEN')
bot.run(TOKEN)