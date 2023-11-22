import time
import json
import re

import telebot
import vk_api
from bs4 import BeautifulSoup
import requests

# токены
from config import VK_TOKEN, token
# чаты тг
from config import ADMIN_CHAT_ID, REPOST_GROUP_CHAT_ID

# группы вк
from config import (
    MY_GROUP_ID,
    MANACOST_GROUP_ID,
    FANNYHS_GROUP_ID,
    OLESYA_GROUP_ID,
    M3S_GROUP_ID
)

# создание бота телеграм и отправка админу сообщения о запуске бота
bot = telebot.TeleBot(token)
bot.send_message(ADMIN_CHAT_ID, "Выполнен запуск бота")

# создание вк сессии
vk_session = vk_api.VkApi(token=VK_TOKEN)
vk = vk_session.get_api()

# Фильтр слов, по которому не отображаются новости сохраняем в файл
# Фильтр плох, его надо полностью переделать в отдельный поток и для разных источников разные фильтры
filefilter = 'filter.json'
# загружаем данные из файла, если файл существует
try:
    with open(filefilter, 'r') as f:
        filter_words = json.load(f)
except FileNotFoundError:
    filter_words = []
    
def save_and_send_posts(group,fpost,chattg):
    '''
    Функция принимает группу, 
    имя файла, в котором сохраняем инфо об уже отправленных постах, 
    чат в который это все отправить.
    Ничего не возвращает, вызывает в своем теле функцию send_post_to_telegram()
    после получения постов из вк.
    '''

    # создаем файл для хранения данных о постах, которые отправляются в группу
    filepost = f"{fpost}.json"
    # загружаем данные из файла, если файл существует, если нет, то создаем пустой словарь
    try:
        with open(filepost, 'r') as f:
            fpost = json.load(f)
    except FileNotFoundError:
        fpost = {}
    
    # Получение последних 10 постов из группы вк
    response = vk.wall.get(owner_id='-' + group, count=10, extended=1, filter='owner')
    #фильтруем рекламу (marked_as_ads)
    posts = [item for item in response['items'] if item.get('marked_as_ads') != 1] 
        
    # Перебор постов в обратном порядке (сначала новые)
    for post in reversed(posts):
    # Если ID поста уже есть в списке отправленных, пропускаем его
        if str(post['id']) in fpost:
            continue
        # получаем текст поста для фильтрации
        text = post['text']
        # тут фильтр. если слово есть в списке фильтров, пропускаем этот пост
        if any(word in text for word in filter_words):
            continue
        # пошлем пост в функцию отправки постов в телегу
        try:
            send_post_to_telegram(post,chattg)
            # пауза на случай, если накопилось много постов
            # без паузы телега заблокирует отправку на некоторое время
            time.sleep(30) 
        except Exception as e:
            # в случае ошибки вы водим ошибку в чат админа и пропускаем пост
            bot.send_message(chat_id=ADMIN_CHAT_ID,text=e)
            pass
        
        # Добавляем ID поста в список отправленных
        fpost[(post['id'])]=(f'[(https://vk.com/wall{post["owner_id"]}_{post["id"]})')
    #Сохраняем отправленные посты в файл        
    with open(filepost, 'w') as f:
        json.dump(fpost, f)


# Функция для отправки сообщения в телеграм
def send_post_to_telegram(post,chat):
    '''
    Функция принимает в себя пост с вк и чат, в который отправить пост.
    Ничего не возвращает, обрабатывает пост и отправляет в телегу. 
    '''
    #получаем инфо о группе для формирования поста
    owner_id = post['owner_id']
    owner_id = str(owner_id).strip("-")
    group_info = vk.groups.getById(group_id=owner_id) 
    group_name = group_info[0]['name']
    group_link = 'https://vk.com/' + group_info[0]['screen_name']
    #формируем ссылку на конкретный пост - будет первой строкой в нашем сообщении
    first_text = f'[{group_name}](https://vk.com/wall{post["owner_id"]}_{post["id"]}):\n'
    
    # тут я пытаюсь по заменить рефер ссылки в постах vk на прямые
    # эту часть можно завернуть в try/except или вообще убрать, если будут проблемы
    if 'text' in post and post['text'] != '':
        fu_url = r'https?://vk\.cc/\S+' #регуляр очка
        urls = re.findall(fu_url, post['text']) #вытягиваем все совпадения
        if urls:
            for url in urls:
                ref_link = requests.get(url) #переходим по ссылке
                time.sleep(1) #на всякий случай
                soup = BeautifulSoup(ref_link.text, features="lxml") #получаем ответ от сайта
                link = soup.find('input')['value'] #ищем там ссылку
                post['text'] = re.sub(url, link, post['text']) #заменяем реф ссылку в посте на прямую
    
    # Еще такие вот ссылки обработаю - у телеги другая разметка 
    # [https://vk.com/wall-66834402_2666522|блаблабла] надо переделать в (описание)[ссылка]
    pattern = r'\[(http[^|\]]+)\|([^]]+)\]'
    post['text'] = re.sub(pattern, r'[\2](\1)', post['text'])
    
    # Разбираемся с вложениями к вк посту
    # Если есть вложения и они не пустые, и первый элемент вложений не пустой
    if 'attachments' in post and post['attachments'] and post['attachments'][0]:
        # все фотки с поста будем складывать в список
        photos = []
        for attachment in post['attachments']:
            # выкачиваем ФОТО из поста и заполняем ими список, 
            # который будем позже отправлять одним сообщением
            if attachment['type'] == 'photo':
                #берем максимальное разрешение
                photo_url = max(attachment['photo']['sizes'], key=lambda x: x['width'])['url']
                #очень большие фотки не лезут почему-то, поэтому берем на размер поменьше
                if "1920x1080" in photo_url:
                    sizes = sorted(attachment['photo']['sizes'], key=lambda x: x['width'])
                    max_size_index = sizes.index(max(sizes, key=lambda x: x['width']))
                    photo_url = (sizes[max_size_index - 1]['url'])
                #добавляем фотку к списку фоток
                photos.append(photo_url)

            # Выкачиваем ссылки ВИДЕО - получаем обложку видео из поста
            # Посты с видео мы сразу же в цикле отправляем с текстом поста
            # Если видео в посте несколько - с каждым видеот отправляется текст поста
            if attachment['type'] == 'video':
                # перебираем разные разрешения превью с большого до малого
                # тут были проблемки взять самое больше разрешение, поэтому такой вот перебор
                if 'photo_1280' in attachment['video']:
                    video_url = attachment['video']['photo_1280']
                elif 'photo_800' in attachment['video']:
                    video_url = attachment['video']['photo_800']
                elif 'photo_320' in attachment['video']:
                    video_url = attachment['video']['photo_320']
                elif 'photo_130' in attachment['video']:
                    video_url = attachment['video']['photo_130']
                # Формируем ссылку на видео
                videourl = f'[Видео](https://vk.com/video{str(attachment["video"]["owner_id"])}_{str(attachment["video"]["id"])})'
                # Если пост с текстом, то прикрепим его к кажому видео
                if 'text' in post and post['text'] != '':
                    # caption = ссылка на пост манакост (first_text), ссылка на [Видео] + подпись
                    try:
                        bot.send_photo(chat_id=chat, photo=video_url,
                                       caption=f'{first_text}\[{videourl}] {post["text"]}',
                                       parse_mode='Markdown')
                    # Из-за возможных проблем с разметкой Markdown сделаем такую обработку ошибок
                    except Exception:
                        bot.send_photo(chat_id=chat, photo=video_url,
                                       caption=f'{first_text}\[{videourl}] {post["text"]}')
                #Без текста просто отсылаем ссылку. В таком случае проблем с Markdown нет
                else:
                    bot.send_photo(chat_id=chat, photo=video_url,
                                   caption=f'{first_text}\[{videourl}]',
                                   parse_mode='Markdown')
        
        # Отправка ФОТО одним сообщением            
        if photos:
            if 'text' in post and post['text'] != '':
                # формируем новый список фоток - в специальном формате для телеги
                mymedia = []
                if len(post['text']) < 1000:
                    # если мало текста, то в описание его запихаем к первой фотке
                    for i, photo in enumerate(photos):
                        if i == 0: # описание в первую фото
                            mymedia.append(telebot.types.InputMediaPhoto(media=photo, 
                                                                         caption=first_text + post['text'], 
                                                                         parse_mode='Markdown'))
                        else: # остальные просто кучкой добавляем рядом
                            mymedia.append(telebot.types.InputMediaPhoto(media=photo))
                    # отправляем
                    try:
                        bot.send_media_group(chat_id=chat, media=mymedia)
                    # если текст кривой - отправим его отдельно 
                    except Exception as e:
                        bot.send_media_group(chat_id=chat, media=[telebot.types.InputMediaPhoto(media=photo) for photo in photos])
                        bot.send_message(chat_id=chat, text=post['text'])
                        
                
                # ежели текста много - сразу отправим его отдельным сообщением
                else:
                    bot.send_media_group(chat_id=chat, media=[telebot.types.InputMediaPhoto(media=photo) for photo in photos])
                    try:
                        bot.send_message(chat_id=chat,text=first_text + post['text'], parse_mode='Markdown')
                    # Маркдаун может подвести из-за кодов колод в тексте, на такой случай второй вариант простенький
                    except Exception:
                        bot.send_message(chat_id=chat,text=first_text + post['text'])
            
            # ежелиже текста нет, то описанием к каждой фотке пускай будет ссылка на фото
            else:
                bot.send_media_group(chat_id=chat, 
                                     media=[telebot.types.InputMediaPhoto(media=photo, 
                                                                          caption = f'{first_text}[Фото]({photo_url})', 
                                                                          parse_mode='Markdown') for photo in photos])
    # Ну и просто текст. 
    # Везде еще обработку на максимальную длину текста надо бы вставлять, 
    # вроде в вк больше символов на пост дает, чем в телеге.
    elif 'text' in post and post['text'] != '':
        #снова обработка ошибок от некорректного текста для Markdown
        try:
            bot.send_message(chat_id=chat, text=first_text + post['text'], parse_mode='Markdown')
        except Exception:
            bot.send_message(chat_id=chat, text=first_text + post['text'])


# Цикл опроса сервера VK на предмет новых постов
while True:
    try: 
        '''
        Вот тут тот самый фильтр, который надо исправить/убрать
        На данный момент при отправдении "/filter lalala" происходит добавление "lalala" в фильтр
        при отправке "/remove lalala" происходит удаление "lalala" из фильтра
        при отправке просто /filter - выводит текущий фильтр.
        Но сделано все неправильно. Надо вставить это в отдельный поток, 
        так как на функцию влияет общая задержка (120 секунд). 
        Так же надо переделать логику, в данный момент, пока админ не отправит команду /ok
        либо другой любой текст после того, как он отправлял команду /filter
        бот будет постоянно отправлять сообщения с текущими фильтрами.
        '''
        updates = bot.get_updates() 
        if updates:
            last_message = updates[-1].message
            #добавляем слово в фильтр
            if (last_message != None) and (last_message.text.startswith('/filter')):
                newfilter = re.sub('/filter', '', last_message.text)
                if (newfilter != '') and (newfilter not in filter_words):
                    filter_words.append(newfilter)
                    with open(filefilter, 'w') as f:
                        json.dump(filter_words, f)
                bot.send_message(chat_id=ADMIN_CHAT_ID,text="Фильтр:" + ', '.join(filter_words))
                bot.send_message(chat_id=ADMIN_CHAT_ID,text='Для выхода нажми /ok')
            #удаляем слово из фильтра
            if  (last_message != None) and (last_message.text.startswith('/remove')):
                delfilter = re.sub('/remove', '', last_message.text)
                if (delfilter != '') and (delfilter in filter_words):
                    filter_words.remove(delfilter)
                    with open(filefilter, 'w') as f:
                        json.dump(filter_words, f)
                bot.send_message(chat_id=ADMIN_CHAT_ID,text="Фильтр:" + ', '.join(filter_words))
                bot.send_message(chat_id=ADMIN_CHAT_ID,text='/ok')

        
        # Собственно часть, где происходит настройка нужной нам отправки
        # save_and_send_posts(группа вк, 'имя файла', чат телеграм)
        save_and_send_posts(MANACOST_GROUP_ID,'manacost_group_posts',REPOST_GROUP_CHAT_ID)
        save_and_send_posts(FANNYHS_GROUP_ID,'funnyhs_posts',ADMIN_CHAT_ID)
        save_and_send_posts(M3S_GROUP_ID,'ms_posts',ADMIN_CHAT_ID)
        save_and_send_posts(MY_GROUP_ID,'test_posts',ADMIN_CHAT_ID)
        save_and_send_posts(OLESYA_GROUP_ID,'olesya_vkzam_posts',ADMIN_CHAT_ID)

        # задержка нужна, так как у вк api есть ограничение на кол-во запросов в день
        # при увеличении количества вызовов функции send_post_to_telegram() задержку нужно будет увеличить
        time.sleep(120) 

    # ошибки присылаем админу
    # в случае переполнения лимита вызывается исключение и бот будет перезапущен
    except Exception as e:
        print(e)
        bot.send_message(chat_id=ADMIN_CHAT_ID,text=e)
        if str(e) == "[29] Rate limit reached":
            raise
