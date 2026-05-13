import streamlit as st
import pandas as pd
import json
import re
from google import genai
from google.genai import types
from supabase import create_client, Client

# 1. 환경 변수 설정 (Streamlit Secrets)
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

# 2. 클라이언트 초기화
genai_client = genai.Client(api_key=GEMINI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 뉴스 검색 및 처리 함수 ---
def search_and_process_news(keyword):
    prompt = f"""
    키워드 '{keyword}'에 대한 가장 최신 뉴스 딱 2건만 검색해줘.
    결과는 반드시 아래 형식을 지킨 JSON 배열로 응답해. 절대 URL을 지어내지 마.
    [
      {{"title": "기사제목", "source": "언론사", "news_date": "YYYY-MM-DD", "url": "원본URL", "summary": "3줄 요약"}}
    ]
    """
    
    # Gemini API 호출 (Google Search Tool 활성화)
    response = genai_client.models.generate_content(
        model="gemini-2.0-flash", # 최신 모델 사용
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearchRetrieval())],
            temperature=0.0
        ),
        contents=prompt
    )

    # 텍스트 응답에서 JSON 추출
    text_response = response.text
    try:
        # Markdown 코드 블록 제거 후 JSON 파싱
        json_str = re.search(r'\[.*\]', text_response, re.DOTALL).group()
        news_data = json.loads(json_str)
    except:
        st.error("AI 응답을 해석하는 데 실패했습니다. 다시 시도해 주세요.")
        return []

    # [URL 환각 방지 로직] Grounding Metadata 활용
    grounding_chunks = getattr(response.candidates[0].grounding_metadata, 'grounding_chunks', [])
    
    for item in news_data:
        for chunk in grounding_chunks:
            if chunk.web:
                real_url = chunk.web.uri
                # 실제 링크가 유효한 경우만 덮어쓰기 (redirect 링크 제외)
                if "grounding-api-redirect" not in real_url and real_url.startswith("http"):
                    # 제목이 유사하거나 포함되면 URL 매칭
                    if item['title'][:10] in chunk.web.title:
                        item['url'] = real_url
                        break
    return news_data

# --- 메인 화면 구성 ---
st.set_page_config(page_title="AI 뉴스 커넥터", layout="wide")
st.title("🗞️ AI 최신 뉴스 검색 & 자동 저장기")

tab1, tab2, tab3 = st.tabs(["🔍 검색하기", "💾 저장된 뉴스 보기", "📊 통계 분석"])

# --- Tab 1: 검색 및 저장 ---
with tab1:
    search_keyword = st.text_input("검색하고 싶은 뉴스 키워드를 입력하세요:", placeholder="예: 삼성전자 주가, 생성형 AI 트렌드")
    if st.button("뉴스 검색 및 저장"):
        if search_keyword:
            with st.spinner("최신 뉴스를 검색하고 분석 중입니다..."):
                results = search_and_process_news(search_keyword)
                
                if results:
                    success_count = 0
                    skip_count = 0
                    
                    for news in results:
                        # 화면 출력
                        with st.container(border=True):
                            st.subheader(news['title'])
                            st.caption(f"{news['source']} | {news['news_date']}")
                            st.write(news['summary'])
                            st.link_button("기사 원문 보기", news['url'])
                        
                        # Supabase 저장
                        try:
                            data = {
                                "keyword": search_keyword,
                                "title": news['title'],
                                "source": news['source'],
                                "news_date": news['news_date'],
                                "url": news['url'],
                                "summary": news['summary']
                            }
                            supabase.table("news_history").insert(data).execute()
                            success_count += 1
                        except Exception as e:
                            # 중복 URL 에러 코드 처리 (23505)
                            skip_count += 1
                    
                    st.toast(f"완료! 새 저장: {success_count}건, 중복 생략: {skip_count}건", icon="✅")
        else:
            st.warning("키워드를 입력해 주세요.")

# --- Tab 2: 저장된 뉴스 보기 ---
with tab2:
    data_response = supabase.table("news_history").select("*").order("created_at", desc=True).execute()
    df = pd.DataFrame(data_response.data)
    
    if not df.empty:
        # 필터링 기능
        search_term = st.text_input("제목 또는 키워드로 검색:", "")
        filtered_df = df[df['title'].str.contains(search_term) | df['keyword'].str.contains(search_term)]
        
        st.dataframe(filtered_df, use_container_width=True)
        
        # CSV 다운로드
        csv = filtered_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("데이터 다운로드(CSV)", data=csv, file_name="news_history.csv", mime="text/csv")
    else:
        st.write("저장된 데이터가 없습니다.")

# --- Tab 3: 통계 분석 ---
with tab3:
    if not df.empty:
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("키워드별 누적 검색 건수")
            keyword_counts = df['keyword'].value_counts()
            st.bar_chart(keyword_counts)
            
        with col2:
            st.subheader("일자별 저장 건수")
            df['created_date'] = pd.to_datetime(df['created_at']).dt.date
            date_counts = df['created_date'].value_counts().sort_index()
            st.line_chart(date_counts)
    else:
        st.write("통계를 낼 데이터가 아직 없습니다.")