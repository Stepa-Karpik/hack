import hashlib
import json
import time
import streamlit as st
from PIL import ImageDraw
from dekanat.schema import SCHEMAS,LABELS,load_policy,validate_policy,ROOT
from dekanat.pipeline import analyze,respond,ANALYSIS_VERSION

st.set_page_config(page_title="Онлайн-деканат",page_icon="📄",layout="wide")
st.title("Онлайн-деканат")
st.caption("Документ → сведения → ответ с основанием")
policy=load_policy()
with st.sidebar:
    st.subheader("Обработка")
    choices=["auto"]+list(SCHEMAS)
    kind=st.selectbox("Тип документа",choices,format_func=lambda x:"Определить автоматически" if x=="auto" else SCHEMAS[x]["title"])
    gpu=st.checkbox("Использовать GPU",value=True)
    retry=st.checkbox("Повторно читать сложные фрагменты",value=True)
    uploaded_policy=st.file_uploader("Заменить Положение (JSON)",type=["json"])
    if uploaded_policy:
        try:
            policy=validate_policy(json.load(uploaded_policy))
        except (ValueError, TypeError) as error:
            st.error(f"Правила не применены: {error}. Используется демонстрационное Положение; образец — configs/policy.demo.json.")
    with st.expander("Положение и происхождение"):
        st.write(policy.get("provenance","Происхождение не указано"))
        for rule in policy["rules"]: st.write(f"**{rule['id']}** — {rule['text']}")
if policy.get("demo"):
    st.info("Используется демонстрационное Положение команды. Настоящее Положение организаторы не предоставили.")
upload=st.file_uploader("Загрузите фото, скан или PDF",type=["png","jpg","jpeg","pdf"])
demo_names={"":"Загрузить свой документ","study":"Справка об обучении","leave":"Академический отпуск","practice":"Справка о практике","study_missing":"Справка с пропущенной датой","study_prose":"Справка: текст и переносы строк","study_sideways":"Справка: поворот на 90°","leave_bad_date":"Заявление: неполная дата",
            "photo_angle":"Справка: съёмка сбоку","photo_light":"Справка: ракурс и тень","photo_blur":"Справка: сильный расфокус","photo_glare":"Справка: засвет"}
demo=st.selectbox("Или выберите учебный пример",list(demo_names),format_func=demo_names.get)
selected_file=upload.name if upload else (f"{demo}.png" if demo else None)
if selected_file:
    data=upload.getvalue() if upload else (ROOT/"data"/"demo"/selected_file).read_bytes()
    if len(data)>25*1024*1024:
        st.error("Максимальный размер файла — 25 МБ.")
        st.stop()
    key=hashlib.sha256(data+f"{ANALYSIS_VERSION}:{kind}:{gpu}:{retry}".encode()).hexdigest()
    if st.button("Распознать документ",type="primary"):
        try:
            with st.spinner("Читаю документ… При первом запуске загружаются веса OCR."):
                pages,result=analyze(data,selected_file,kind,gpu,retry)
            st.session_state.document={"key":key,"pages":pages,"analysis":result,"filename":selected_file}
        except Exception as error:
            st.error(f"Не удалось обработать документ: {error}")
    document=st.session_state.get("document")
    if document and document["key"]==key:
        result=document["analysis"]
        if result.get("error"): st.warning(result["error"])
        left,right=st.columns([1,1])
        with left:
            page_id=st.selectbox("Страница",range(len(document["pages"])),format_func=lambda x:str(x+1))
            preview=document["pages"][page_id].copy()
            draw=ImageDraw.Draw(preview)
            for field in result["fields"].values():
                evidence=field.get("evidence")
                if evidence and evidence.get("page")==page_id:
                    draw.rectangle(evidence["bbox"],outline="#2563eb" if field["status"]=="found" else "#d97706",width=3)
            st.image(preview,width="stretch")
            correction=result.get("preprocessing",[])
            if correction:
                meta=correction[page_id]
                if meta.get("orientation",{}).get("applied"):
                    st.caption(f"Страница повёрнута на {meta['orientation']['degrees_ccw']}°, чтобы текст читался правильно. Рамки показаны на исправленной странице.")
                if meta.get("perspective",{}).get("applied"):
                    st.caption("Перспектива исправлена по четырём углам листа. Рамки показаны на выровненной странице.")
                if meta.get("lighting",{}).get("applied"):
                    st.caption("Для OCR скорректировано неравномерное освещение; цветной оригинал сохранён для просмотра и поиска отметок.")
                for warning in meta.get("quality",{}).get("warnings",[]):
                    st.warning(warning)
            if correction and correction[page_id]["rotation_degrees"]:
                st.caption(f"Страница выровнена на {correction[page_id]['rotation_degrees']:.1f}°. Рамки показаны на выровненном изображении.")
        with right:
            st.subheader(SCHEMAS[result["type"]]["title"] if result["type"] else "Документ")
            table=[]
            statuses={"found":"Найдено","not_found":"Не найдено","uncertain":"Нужна проверка","conflict":"Противоречие"}
            for key_field,field in result["fields"].items():
                value=field["value"]
                if key_field in SCHEMAS[result["type"]]["visual"] and field["status"]!="found":
                    value="Не подтверждено"
                elif isinstance(value,bool): value="Обнаружено" if value else "Не обнаружено; нужна проверка"
                source="—" if value is None else "Текст PDF" if (field.get("evidence") or {}).get("source")=="visible_pdf_text" else "Изображение"
                table.append({"Поле":LABELS[key_field],"Значение":value if value is not None else "не найдено","Статус":statuses[field["status"]],"Источник":source})
            st.dataframe(table,hide_index=True,width="stretch")
            if result.get("native_pdf",{}).get("applied"):
                st.caption("Пустые поля дополнены текстом PDF. Эти значения требуют сверки с документом.")
            date_changes=result.get("field_validation",{}).get("changes",[])
            for change in date_changes:
                if change["action"]=="review_required":
                    st.warning(f"{LABELS[change['field']]}: {change['reason']}")
            if any(change["action"]=="normalized" for change in date_changes):
                st.caption("Разделители дат приведены к единому виду. Исходное чтение сохранено в результате JSON.")
            st.caption(f"Обработка: {result['seconds']:.2f} с · повторных чтений: {result['ocr']['retries']}")
            st.caption("Визуальные отметки: реальные подписи + синтетика. Качество печатей на реальных фото ещё не измерено; подлинность не проверяется.")
            st.caption("Если блик закрывает текст, нужна пересъёмка. Автоматическая проверка качества не обнаруживает все засветы. Для исправления перспективы нужны все четыре угла листа и контрастный фон.")
            question=st.text_input("Вопрос",value="Все ли обязательные сведения есть в документе?")
            reply_key=hashlib.sha256((document["key"]+question+json.dumps(policy,ensure_ascii=False,sort_keys=True)).encode()).hexdigest()
            if st.button("Получить ответ",type="primary"):
                started=time.perf_counter()
                reply=respond(result,question,policy)
                st.session_state.reply={"key":reply_key,"value":reply,"milliseconds":(time.perf_counter()-started)*1000}
            saved_reply=st.session_state.get("reply")
            if saved_reply and saved_reply["key"]==reply_key:
                reply=saved_reply["value"]
                if reply["status"]=="complete":st.success(reply["answer"])
                elif reply["status"]=="insufficient":st.warning(reply["answer"])
                else:st.info(reply["answer"])
                for source in reply["sources"]:
                    if source["kind"]=="policy": st.caption(f"Основание: п. {source['id']} — {source['text']}")
                    else: st.caption("Источник: поле «"+LABELS[source["id"]]+"» документа")
                st.caption(f"Ответ: {saved_reply['milliseconds']:.1f} мс; повторное OCR не выполнялось")
                export={"document":document["filename"],"question":question,"policy":policy["title"],"demo_policy":policy.get("demo",False),**result,"response":reply}
                # OpenCV may return NumPy scalars/arrays in visual geometry.
                st.download_button("Скачать результат JSON",json.dumps(export,ensure_ascii=False,indent=2,default=lambda value:value.tolist()),file_name="result.json",mime="application/json")
            with st.expander("Распознанный текст"):
                st.text("\n".join(x["text"] for x in result["ocr"]["lines"]))
            recovery=result["ocr"].get("quote_recovery",{})
            if recovery.get("lines"):
                with st.expander("Перечитанные фрагменты"):
                    st.text("\n".join(x["text"] for x in recovery["lines"]))

