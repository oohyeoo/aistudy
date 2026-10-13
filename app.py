import os
import sqlite3
import hmac
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="배움로그", page_icon="📚", layout="wide")
DB = Path(os.environ.get("BAEUMLOG_DB", "baeumlog.db"))


def conn():
    c = sqlite3.connect(DB, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS classes(id INTEGER PRIMARY KEY, name TEXT NOT NULL, code TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS students(id INTEGER PRIMARY KEY, class_id INTEGER NOT NULL REFERENCES classes(id), code TEXT NOT NULL, UNIQUE(class_id,code));
        CREATE TABLE IF NOT EXISTS lessons(id INTEGER PRIMARY KEY, class_id INTEGER NOT NULL REFERENCES classes(id), title TEXT NOT NULL, concept TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, published INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY, lesson_id INTEGER NOT NULL REFERENCES lessons(id), prompt TEXT NOT NULL, a TEXT NOT NULL, b TEXT NOT NULL, c TEXT NOT NULL, d TEXT NOT NULL, correct TEXT NOT NULL, explanation TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES students(id), lesson_id INTEGER NOT NULL REFERENCES lessons(id), attempt_no INTEGER NOT NULL, submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(student_id,lesson_id,attempt_no));
        CREATE TABLE IF NOT EXISTS answers(id INTEGER PRIMARY KEY, attempt_id INTEGER NOT NULL REFERENCES attempts(id), question_id INTEGER NOT NULL REFERENCES questions(id), selected TEXT NOT NULL, is_correct INTEGER NOT NULL, UNIQUE(attempt_id,question_id));
        CREATE TABLE IF NOT EXISTS reflections(id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES students(id), lesson_id INTEGER NOT NULL REFERENCES lessons(id), body TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(student_id,lesson_id));
        """)
        if not c.execute("SELECT 1 FROM classes LIMIT 1").fetchone():
            c.execute("INSERT INTO classes(name,code) VALUES(?,?)", ("2학년 3반", "KOR203"))
            class_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
            c.execute("INSERT INTO lessons(class_id,title,concept) VALUES(?,?,?)", (class_id, "매체 자료의 비판적 이해", "근거를 활용한 의미 구성"))
            lid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
            samples = [
                ("같은 글을 읽고 서로 다르게 해석할 수 있는 이유는?", "글의 의미는 언제나 하나이기 때문", "독자의 경험과 배경지식이 다를 수 있기 때문", "모든 해석이 근거 없이 옳기 때문", "글을 읽는 속도가 같기 때문", "B", "독자는 배경지식을 활용해 의미를 구성하지만, 해석에는 텍스트 근거가 필요합니다."),
                ("매체 자료의 신뢰성을 판단할 때 가장 먼저 살펴볼 것은?", "화려한 디자인", "조회 수", "자료의 출처와 근거", "제목의 길이", "C", "정보의 출처, 근거의 타당성과 작성 맥락을 확인해야 합니다."),
                ("글의 해석을 설득력 있게 설명하는 방법은?", "자신의 느낌만 반복한다", "본문의 표현과 장면을 근거로 제시한다", "친구의 해석을 무조건 따른다", "정답이라고 주장한다", "B", "해석은 텍스트의 구체적인 표현과 내용에 연결되어야 설득력이 높아집니다."),
            ]
            c.executemany("INSERT INTO questions(lesson_id,prompt,a,b,c,d,correct,explanation) VALUES(?,?,?,?,?,?,?,?)", [(lid,*x) for x in samples])


def query(sql, args=()):
    with conn() as c:
        return c.execute(sql,args).fetchall()


def execute(sql,args=()):
    with conn() as c:
        c.execute(sql,args)


def lesson_questions(lid):
    return query("SELECT * FROM questions WHERE lesson_id=? ORDER BY id", (lid,))


def results(student_id):
    return query("""SELECT l.id lesson_id,l.title,l.concept,a.attempt_no,a.submitted_at,
        COUNT(ans.id) total,COALESCE(SUM(ans.is_correct),0) correct
        FROM attempts a JOIN lessons l ON l.id=a.lesson_id
        LEFT JOIN answers ans ON ans.attempt_id=a.id
        WHERE a.student_id=? GROUP BY a.id ORDER BY a.submitted_at,a.id""",(student_id,))


def submit_attempt(student_id, lesson_id, choices):
    qs = lesson_questions(lesson_id)
    if not qs or set(choices) != {q['id'] for q in qs}:
        raise ValueError("모든 문항에 응답해야 합니다.")
    with conn() as c:
        next_no = c.execute("SELECT COALESCE(MAX(attempt_no),0)+1 FROM attempts WHERE student_id=? AND lesson_id=?",(student_id,lesson_id)).fetchone()[0]
        c.execute("INSERT INTO attempts(student_id,lesson_id,attempt_no) VALUES(?,?,?)",(student_id,lesson_id,next_no))
        aid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.executemany("INSERT INTO answers(attempt_id,question_id,selected,is_correct) VALUES(?,?,?,?)", [(aid,q['id'],choices[q['id']],int(choices[q['id']]==q['correct'])) for q in qs])
    return next_no


def student_app():
    st.header("👩‍🎓 학생 학습 공간")
    if 'student_id' not in st.session_state:
        with st.form("student_login"):
            code = st.text_input("학급 코드", placeholder="예: KOR203").strip().upper()
            student_code = st.text_input("학생 코드 (개인별 식별 코드)", placeholder="예: S001").strip()
            go = st.form_submit_button("입장하기")
        if go:
            classes = query("SELECT * FROM classes WHERE code=?",(code,))
            if not classes or not student_code:
                st.error("학급 코드와 학생 코드를 확인해 주세요.")
            else:
                cid=classes[0]['id']
                execute("INSERT OR IGNORE INTO students(class_id,code) VALUES(?,?)",(cid,student_code))
                row=query("SELECT id FROM students WHERE class_id=? AND code=?",(cid,student_code))[0]
                st.session_state.student_id=row['id']
                st.session_state.class_id=cid
                st.rerun()
        return
    sid=st.session_state.student_id
    cid=st.session_state.class_id
    if st.button("로그아웃",key="student_logout"):
        for key in ['student_id','class_id']:
            st.session_state.pop(key,None)
        st.rerun()
    tabs=st.tabs(["오늘의 학습","나의 성장","오답 노트","배움 일지"])
    lessons=query("SELECT * FROM lessons WHERE class_id=? AND published=1 ORDER BY id DESC",(cid,))
    with tabs[0]:
        if not lessons:
            st.info("공개된 학습이 없습니다.")
        else:
            selected=st.selectbox("학습 선택",lessons,format_func=lambda l:l['title'],key="lesson_select")
            lid=selected['id']
            st.caption(f"핵심 개념: {selected['concept']}")
            qs=lesson_questions(lid)
            if not qs:
                st.warning("등록된 문항이 없습니다.")
            else:
                with st.form(f"quiz_{lid}"):
                    choices={}
                    for i,q in enumerate(qs,1):
                        st.markdown(f"**{i}. {q['prompt']}**")
                        opts={k:q[k.lower()] for k in 'ABCD'}
                        choice=st.radio("답 선택",list(opts),format_func=lambda k:f"{k}. {opts[k]}",index=None,key=f"q_{lid}_{q['id']}")
                        if choice: choices[q['id']]=choice
                    submitted=st.form_submit_button("제출하고 피드백 보기",type="primary")
                if submitted:
                    if len(choices)!=len(qs):
                        st.warning("모든 문항에 응답해 주세요.")
                    else:
                        no=submit_attempt(sid,lid,choices)
                        st.session_state['feedback']=(lid,no,choices)
                feedback=st.session_state.get('feedback')
                if feedback and feedback[0]==lid:
                    _,no,answers=feedback
                    score=sum(answers.get(q['id'])==q['correct'] for q in qs)
                    st.success(f"{no}차 시도: {score}/{len(qs)}문항 정답")
                    for q in qs:
                        ok=answers.get(q['id'])==q['correct']
                        st.markdown(f"{'✅' if ok else '❌'} **{q['prompt']}**")
                        st.write(f"정답: {q['correct']} · {q['explanation']}")
                    st.info("다시 제출하면 새로운 시도로 저장됩니다. 첫 시도 결과는 그대로 유지됩니다.")
    with tabs[1]:
        rows=results(sid)
        if rows:
            df=pd.DataFrame([dict(r) for r in rows]); df['정답률(%)']=(100*df['correct']/df['total'].clip(lower=1)).round(1)
            st.metric("학습 참여 차시",df['lesson_id'].nunique())
            first=df[df['attempt_no']==1].copy()
            st.metric("첫 시도 평균 정답률",f"{first['정답률(%)'].mean():.1f}%")
            first['학습 순서']=range(1,len(first)+1)
            st.line_chart(first.set_index('학습 순서')['정답률(%)'])
            st.dataframe(df[['title','concept','attempt_no','correct','total','정답률(%)','submitted_at']].rename(columns={'title':'학습','concept':'핵심 개념','attempt_no':'시도','correct':'정답 수','total':'문항 수','submitted_at':'제출 시각'}),hide_index=True)
        else: st.info("학습에 참여하면 성장 기록이 표시됩니다.")
    with tabs[2]:
        wrong=query("""SELECT l.title,q.prompt,q.correct,q.explanation,ans.selected,a.submitted_at
            FROM answers ans JOIN attempts a ON a.id=ans.attempt_id
            JOIN questions q ON q.id=ans.question_id JOIN lessons l ON l.id=a.lesson_id
            WHERE a.student_id=? AND ans.is_correct=0 ORDER BY a.id DESC""",(sid,))
        if wrong:
            for r in wrong:
                with st.expander(f"{r['title']} · {r['prompt']}"):
                    st.write(f"내 답: {r['selected']} / 정답: {r['correct']}")
                    st.write(r['explanation'])
            st.caption("오답은 이력으로 보존됩니다. 같은 학습에서 재도전할 수 있습니다.")
        else: st.info("아직 오답 기록이 없습니다.")
    with tabs[3]:
        if lessons:
            chosen=st.selectbox("배움 일지를 작성할 학습",lessons,format_func=lambda l:l['title'],key="reflection_lesson")
            previous=query("SELECT body FROM reflections WHERE student_id=? AND lesson_id=?",(sid,chosen['id']))
            body=st.text_area("오늘 배운 점, 헷갈리는 점, 질문",value=previous[0]['body'] if previous else '',key=f"reflection_{chosen['id']}")
            if st.button("배움 일지 저장"):
                if body.strip():
                    execute("INSERT INTO reflections(student_id,lesson_id,body) VALUES(?,?,?) ON CONFLICT(student_id,lesson_id) DO UPDATE SET body=excluded.body,created_at=CURRENT_TIMESTAMP",(sid,chosen['id'],body.strip()))
                    st.success("저장되었습니다.")
                else: st.warning("내용을 입력해 주세요.")


def teacher_app():
    st.header("👩‍🏫 교사 관리 공간")
    password=os.environ.get('BAEUMLOG_TEACHER_PASSWORD','')
    if not password:
        st.error("교사 로그인이 비활성화되어 있습니다. BAEUMLOG_TEACHER_PASSWORD 환경변수를 설정하세요.")
        return
    if not st.session_state.get('teacher_auth'):
        with st.form('teacher_login'):
            entered=st.text_input('교사 비밀번호',type='password')
            if st.form_submit_button('로그인'):
                if hmac.compare_digest(entered,password):
                    st.session_state.teacher_auth=True; st.rerun()
                else: st.error('비밀번호가 올바르지 않습니다.')
        return
    if st.button('교사 로그아웃'):
        st.session_state.teacher_auth=False; st.rerun()
    classes=query("SELECT * FROM classes ORDER BY id")
    selected=st.selectbox('학급',classes,format_func=lambda x:f"{x['name']} ({x['code']})")
    cid=selected['id']
    tabs=st.tabs(['학급 대시보드','문제 관리','학생별 분석','배움 일지 확인','학급 관리'])
    with tabs[0]:
        students=query('SELECT * FROM students WHERE class_id=?',(cid,))
        first=query("""SELECT a.student_id,l.title,COUNT(ans.id) total,SUM(ans.is_correct) correct
            FROM attempts a JOIN lessons l ON l.id=a.lesson_id JOIN answers ans ON ans.attempt_id=a.id
            WHERE l.class_id=? AND a.attempt_no=1 GROUP BY a.id""",(cid,))
        c1,c2,c3=st.columns(3)
        c1.metric('등록 학생',len(students))
        c2.metric('첫 시도 참여 건수',len(first))
        c3.metric('첫 시도 평균 정답률',f"{sum(r['correct'] for r in first)/sum(r['total'] for r in first)*100:.1f}%" if first else '—')
        if first:
            df=pd.DataFrame([dict(r) for r in first]); df['정답률(%)']=df['correct']/df['total']*100
            st.subheader('학습별 평균 정답률')
            st.bar_chart(df.groupby('title')['정답률(%)'].mean())
        per_question=query("""SELECT q.prompt,COUNT(ans.id) submissions,ROUND(100.0*SUM(ans.is_correct)/COUNT(ans.id),1) rate
            FROM answers ans JOIN attempts a ON a.id=ans.attempt_id JOIN questions q ON q.id=ans.question_id
            JOIN lessons l ON l.id=q.lesson_id WHERE l.class_id=? AND a.attempt_no=1
            GROUP BY q.id ORDER BY rate ASC""",(cid,))
        if per_question:
            st.subheader('문항별 첫 시도 정답률')
            st.dataframe(pd.DataFrame([dict(r) for r in per_question]).rename(columns={'prompt':'문항','submissions':'응답 수','rate':'정답률(%)'}),hide_index=True)
    with tabs[1]:
        st.subheader('학습 만들기')
        with st.form('add_lesson'):
            title=st.text_input('학습 제목')
            concept=st.text_input('핵심 개념')
            published=st.checkbox('학생에게 공개',value=True)
            if st.form_submit_button('학습 등록'):
                if title.strip() and concept.strip():
                    execute('INSERT INTO lessons(class_id,title,concept,published) VALUES(?,?,?,?)',(cid,title.strip(),concept.strip(),int(published)))
                    st.success('등록되었습니다.'); st.rerun()
                else: st.warning('제목과 핵심 개념을 입력해 주세요.')
        lessons=query('SELECT * FROM lessons WHERE class_id=? ORDER BY id DESC',(cid,))
        if lessons:
            lesson=st.selectbox('문항을 등록할 학습',lessons,format_func=lambda x:x['title'],key='teacher_lesson')
            st.caption('기존 문항은 학습 기록의 일관성을 위해 삭제·수정하지 않습니다. 새 문항은 다음 응시부터 반영됩니다.')
            with st.form('add_question'):
                prompt=st.text_input('문제')
                options={k:st.text_input(f'{k} 선택지') for k in 'ABCD'}
                correct=st.selectbox('정답',list('ABCD'))
                explanation=st.text_area('정답 해설')
                if st.form_submit_button('문항 등록'):
                    if prompt.strip() and explanation.strip() and all(x.strip() for x in options.values()):
                        execute('INSERT INTO questions(lesson_id,prompt,a,b,c,d,correct,explanation) VALUES(?,?,?,?,?,?,?,?)',(lesson['id'],prompt.strip(),*[options[k].strip() for k in 'ABCD'],correct,explanation.strip()))
                        st.success('문항이 등록되었습니다.'); st.rerun()
                    else: st.warning('모든 항목을 입력해 주세요.')
            for q in lesson_questions(lesson['id']):
                st.write(f"• {q['prompt']} (정답 {q['correct']})")
    with tabs[2]:
        students=query('SELECT * FROM students WHERE class_id=? ORDER BY code',(cid,))
        if students:
            student=st.selectbox('학생 코드',students,format_func=lambda x:x['code'])
            rows=results(student['id'])
            if rows:
                df=pd.DataFrame([dict(r) for r in rows]); df['정답률(%)']=(100*df['correct']/df['total'].clip(lower=1)).round(1)
                st.dataframe(df[['title','attempt_no','correct','total','정답률(%)','submitted_at']],hide_index=True)
            else: st.info('아직 학습 기록이 없습니다.')
        else: st.info('등록된 학생이 없습니다.')
    with tabs[3]:
        reflections=query("""SELECT s.code student_code,l.title,r.body,r.created_at FROM reflections r
            JOIN students s ON s.id=r.student_id JOIN lessons l ON l.id=r.lesson_id
            WHERE s.class_id=? ORDER BY r.created_at DESC""",(cid,))
        if reflections: st.dataframe(pd.DataFrame([dict(r) for r in reflections]),hide_index=True)
        else: st.info('작성된 배움 일지가 없습니다.')
    with tabs[4]:
        with st.form('add_class'):
            name=st.text_input('새 학급 이름')
            code=st.text_input('새 학급 코드')
            if st.form_submit_button('학급 만들기'):
                if name.strip() and code.strip():
                    try:
                        execute('INSERT INTO classes(name,code) VALUES(?,?)',(name.strip(),code.strip().upper()))
                        st.success('학급이 만들어졌습니다.'); st.rerun()
                    except sqlite3.IntegrityError: st.error('이미 사용 중인 학급 코드입니다.')
                else: st.warning('학급 이름과 코드를 입력해 주세요.')
        st.caption('학생 코드는 최초 접속 시 자동 등록됩니다. 코드를 아는 사람은 같은 기록에 접근할 수 있으므로 실사용 전 별도 인증을 도입하세요.')


init_db()
st.title('📚 배움로그')
st.caption('수업마다 확인하고, 피드백으로 성장하는 학습 기록장')
role=st.sidebar.radio('이용 공간',['학생','교사'])
if role=='학생': student_app()
else: teacher_app()
