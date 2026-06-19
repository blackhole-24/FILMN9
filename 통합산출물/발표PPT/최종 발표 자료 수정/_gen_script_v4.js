const fs=require('fs');
const {Document,Packer,Paragraph,TextRun,HeadingLevel,AlignmentType,BorderStyle,PageBreak}=require('docx');
const F="맑은 고딕", NAVY="0E2742", GOLD="B5872B", INK="1A2430", GRAY="5A6573", GREEN="1A6E47";

// 슬라이드별 발표 멘트 (부드럽게·비유)
const SLIDES=[
["표지","🎙 “안녕하세요. 저희는 ‘전문가의 정보를, 모두에게’ 라는 생각에서 출발한 FINSIGHT입니다. 어려운 기업 정보를 누구나 쉽게, 그리고 반드시 출처와 함께 볼 수 있게 만든, AI 기반 기업 분석·가치 평가 정보 서비스입니다.”"],
["목차","🎙 “오늘은 여덟 단계로 말씀드리겠습니다. 왜 만들었는지, 어떻게 만들었는지, 누가 만들었는지, 그리고 어떻게 운영·수익으로 이어지는지 — 마지막엔 실제 서비스에 직접 접속해 보여드리겠습니다.”"],
["기획 배경 · 페르소나","🎙 “요즘은 누구나 주식을 시작합니다. 그런데 막상 시작하면 벽에 부딪힙니다. 정보는 사방에 흩어져 있죠 — 공시는 DART, 시세는 증권앱, 뉴스는 포털. 매번 창을 옮겨 다녀야 합니다. 용어는 외국어처럼 어렵고, 유튜브·단톡방 정보는 출처가 없어 믿기 어렵습니다. 결국 ‘비싼지 싼지’조차 감으로 판단하게 되죠.”",
 "🎙 “저희는 이 ‘정보 비대칭’을 조금이라도 줄이고 싶었습니다. 거짓 없는 신뢰 정보만 모아, 누구나 스스로 옳고 그름을 판단할 수 있게요. 이 네 가지 문제를 FINSIGHT가 어떤 정보로 푸는지는 — 잠시 후 실제 화면으로 하나씩 직접 보여드리겠습니다.”  (★해결방안은 시연 때 말로 연결)"],
["WBS","🎙 “약 두 달, 다섯 개의 스프린트로 만들었습니다. 멘토링 피드백을 네 번 반영했고요. 초반엔 기획·요구사항을 함께 다졌고, 스프린트 2부터는 기업분석 파트와 밸류에이션 파트로 나눠 동시에 개발했습니다. 한쪽은 재무·브리핑·관리자를, 다른 한쪽은 밸류 엔진·챗봇을 맡아 끝까지 병행했습니다.”"],
["시스템 아키텍처","🎙 “전체 구조를 큰 그림으로 보겠습니다. 사용자가 접속하면 AWS 클라우드 안의 서버가 받습니다. 먼저 nginx라는 ‘문지기’가 요청을 안전한 https로 바꿔 안으로 넘기고, FastAPI라는 ‘주방’이 실제 데이터를 요리해 화면으로 내보냅니다.”",
 "🎙 “데이터는 성격에 따라 네 군데에 나눠 담습니다 — 표 형태는 RDS, 회사 이야기는 MongoDB, AI 검색용은 ChromaDB, 그림·파일은 S3. 그리고 AI 챗봇은 GPU가 필요해서, 평소엔 꺼 두고 시연할 때만 켜는 별도 서버로 분리했습니다. 비용을 아끼는 구조죠.”  (★PM 산출물: 큰 흐름 강조)"],
["데이터 파이프라인","🎙 “데이터가 어떻게 흘러 화면까지 오는지, 정수기에 비유해 다섯 단계로 보겠습니다. ① 먼저 공식 출처에서 원수를 길어 옵니다 — DART 공시, 거래소 시세, 한국은행 금리. ② 정제합니다 — 들쭉날쭉한 재무를 표준화하고, 밸류·브리핑·임베딩을 만들죠.”",
 "🎙 “③ 핵심은 검증입니다 — 원문과 대조하고, 없으면 가짜로 채우지 않고 ‘없음’으로 둡니다. 저희 NO-MOCK 원칙이에요. ④ 검증된 물만 네 저장소에 담고 ⑤ API로 화면에 내보냅니다. 주가처럼 매일 바뀌는 건 자동 배치로, 시세·뉴스는 실시간으로 — 성격에 맞게 갱신합니다.”"],
["ERD","🎙 “데이터 구조입니다. 가운데 ‘회사 기본정보’가 뿌리이고, 종목코드 하나로 재무·주가·주주·임원·공시·밸류가 전부 연결됩니다. 관계형으로 딱 맞는 16개 표는 RDS에, 회사 이야기 같은 자유로운 글은 MongoDB, AI 검색용 벡터는 ChromaDB, 그림은 S3 — 데이터 성격에 맞는 저장소를 골라 분산했습니다.”"],
["기술 스택","🎙 “기술은 화면부터 인프라까지 전 계층을 직접 구축했습니다. 화면은 Next.js, 서버는 FastAPI, 데이터는 네 종류 DB, AI는 OpenAI와 임베딩 모델, 인프라는 AWS입니다. 각 기술을 왜 골랐는지는 질문 주시면 말씀드리겠습니다. 핵심 철학 하나만 — AI는 ‘찾기’만 맡기고 ‘판단’은 사람이 짠 규칙이 합니다. 그래야 AI가 거짓을 지어내지 못하니까요.”  (★선택 근거·Q&A는 본문 Part 3)"],
["팀 구성","🎙 “세 명이 만들었습니다. 저는 PM과 공통, 그리고 기업분석 화면을 맡았고, 고휘주 님은 AI 히스토리 브리핑과 계열사 시각화를, 유태상 님은 밸류에이션과 AI 챗봇을 맡았습니다.”  (★짧고 핵심만 — 시간 절약)"],
["비즈니스 모델","🎙 “비용과 수익입니다. 개발 원가는 인건비 포함 약 2,450만 원으로 추산했고, AI 운영비는 로컬 GPU와 AWS 크레딧으로 거의 0에 가깝게 줄였습니다.”",
 "🎙 “수익은 구독입니다. 기본은 무료, 심층 밸류·적정가 알림·챗봇 무제한은 Pro로요. 가정해 보면 Pro 월 9,900원에 약 21명만 모으면 운영비 손익분기이고, 300명이면 개발 원가를 약 9개월에 회수합니다. 고정비가 작아 손익분기점이 낮은 구조입니다.”"],
["밸류에이션 ① 상대가치","🎙 “지금부터가 저희 서비스의 핵심, 밸류에이션입니다. ‘이 주식, 지금 비싼가 싼가’를 보는 첫 번째 방법은 ‘옆집과 비교’예요. 우리 집 값을 알려면 옆집 시세를 봐야 하듯, 한 회사만 보면 비싼지 알 수 없고 비슷한 회사들과 견줘야 합니다.”",
 "🎙 “그 비교의 자가 멀티플 — PER, EV/EBITDA 같은 ‘가격 배수’입니다. 예컨대 PER은 ‘지금 가격이 그 회사가 1년 버는 돈의 몇 배냐’인데, 쉽게는 ‘이익이 그대로면 원금 회수에 몇 년 걸리나’예요. 비슷한 회사들의 가운뎃값을 우리 회사에 적용해 적정가를 거꾸로 계산합니다.”",
 "🎙 “여기서 ‘누구와 비교하느냐’가 평가의 절반입니다. 그래서 저흰 업종·규모·사업 내용 등 열 가지를 점수로 매겨 자동으로 고르고, 그 선정이 얼마나 잘 됐는지를 A부터 E까지 등급으로 솔직하게 공개합니다.”"],
["밸류에이션 ② 절대가치 (DCF)","🎙 “두 번째 방법은 ‘이 회사가 앞으로 벌 돈을 직접 계산’하는 DCF입니다. 사과나무에 비유하면 — 나무의 가치는 앞으로 맺을 사과를 다 합친 것이죠. 단, 내년 사과는 올해 사과보다 가치가 작으니, 기다림과 불확실성만큼 할인해서 더합니다.”",
 "🎙 “그 할인율이 WACC인데, ‘돈을 끌어다 쓰는 평균 비용’이자 ‘회사가 최소한 넘어야 할 합격선’입니다. 중요한 건, 저흰 DCF 값을 하나의 숫자로 못 박지 않습니다. 가정에 민감하니까 비관·기본·낙관 ‘범위’로 보여줘요.”",
 "🎙 “그리고 DCF 값이 현재 주가와 다를 때, 그 차이를 ‘틀렸다’가 아니라 ‘시장이 이 회사에 건 기대’로 해석합니다. 신뢰도가 낮으면 적정가 숫자를 일부러 숨겨, 사람들이 틀린 숫자에 매달리지 않게 하고요. 한마디로 — 정답 가격을 주는 게 아니라, 스스로 판단할 근거를 투명하게 드리는 겁니다.”"],
["AWS 배포 시연","🎙 “자, 이제 말로 설명한 모든 걸 실제 서비스로 보여드리겠습니다. 지금 보시는 건 데모 화면이 아니라, AWS에 배포된 진짜 서비스입니다.”  (→ 라이브 시연으로 전환)"],
["마무리","🎙 “정리하면 — 저흰 거짓 없는 팩트만, 출처와 함께, 어려운 걸 쉽게 풀어, 누구나 스스로 판단하도록 돕습니다. 전문가의 정보를, 모두에게. 감사합니다.”"],
];

// Part 2: AI 기술 활용 + 화면 매핑
const AI=[
["LLM (OpenAI gpt-5-mini)","사업보고서를 쉬운 말로 요약 / 챗봇 답변 생성 / (밸류) 신용등급 추출","기업분석 탭 ‘히스토리 브리핑’, AI 챗봇 탭, 밸류 WACC 내부계산"],
["RAG (검색증강생성)","사업보고서를 검색해 ‘출처와 함께’ 답을 생성 — 없으면 ‘없음’","AI 챗봇 탭, 히스토리 브리핑"],
["임베딩 (BGE-M3, 1024차원)","‘사업의 내용’을 숫자 벡터로 바꿔 회사 간 사업 유사도 측정 / 챗봇 검색","밸류 ‘피어기업 선정’(사업유사도), AI 챗봇 검색"],
["리랭커 (bge-reranker-v2-m3)","RAG 검색 결과를 다시 순위 매겨 정확도를 높임","AI 챗봇 답변 정확도"],
["온톨로지 (WICS 산업분류 + 사업 도메인 태그)","업종 계층·인접 업종 관계로 ‘같은/닮은 업종’ 판단 + 고객사·경쟁사·사업방식 관계 정의","밸류 ‘피어 선정’(업종18%·BIZ_TAG), 히스토리 ‘고객사·경쟁사’, 산업분류 탭"],
["(비전/이미지)","계열사 소유지분도는 DART 원본 이미지·SVG를 그대로 제공 (별도 비전 모델 분석은 미적용)","기업분석 탭 ‘계열사 관계도’"],
];

// Part 3: 기술 스택 선택 근거 & 예상 Q&A
const TECH=[
["Next.js (프론트)","정적·동적 렌더를 섞어 초기 로딩이 빠르고, 한 프레임워크로 화면·라우팅을 일관되게. React 생태계로 개발 속도↑."],
["FastAPI (백엔드)","데이터·AI 라이브러리가 전부 Python이라 백엔드도 Python이 자연스럽고, 비동기로 동시 요청을 빠르게 처리. 자동 API 문서화."],
["PostgreSQL / RDS","재무 항등식 같은 관계형 정합성 보장 + 주가 1천만 행도 안정적. 관리형이라 백업·보안 자동."],
["MongoDB Atlas","회사별 ‘이야기’(브리핑)는 형식이 자유로워 스키마 유연한 문서형이 적합."],
["ChromaDB","벡터 검색 전용 DB. 로컬 GPU와 붙여 임베딩 검색을 무료로 운영."],
["OpenAI gpt-5-mini","비용 대비 한국어 요약·대화 품질이 우수하고, 질의당 약 5원으로 저렴."],
["BGE-M3 임베딩","다국어(한국어에 강함) 오픈 모델. 로컬 GPU로 무료 운영 → 운영비 절감."],
["AWS (EC2·RDS·S3)","크레딧 활용 + 표준 인프라 + 확장 용이. GPU는 챗봇 전용 인스턴스로 분리해 평소엔 꺼 비용 최소화."],
["nginx + Let's Encrypt","무료 HTTPS 인증서 + 리버스 프록시로 보안·라우팅을 한 번에."],
];
const QA=[
["AI가 거짓(할루시네이션)을 지어내면?","AI는 ‘찾기’만 맡고 ‘판단’은 정해진 규칙이 합니다. 모든 답에 출처를 붙이고, 자료에 없으면 ‘없음’으로 두며, 신뢰도가 낮으면 숫자를 일부러 숨깁니다."],
["왜 LangChain을 안 썼나요?","검색·생성 파이프라인을 직접 구현해 동작을 완전히 통제하고, 불필요한 추상화와 의존성을 줄이기 위해서입니다."],
["데이터는 얼마나 최신인가요?","주가는 매 거래일 16시에 자동 갱신, 재무·공시는 분기 보고서가 나올 때 갱신합니다. 관리자 화면에서 갱신 시각을 실측으로 확인할 수 있습니다."],
["DCF 적정가가 현재 주가와 많이 다르면?","그 차이를 ‘오류’가 아니라 ‘시장의 기대’로 해석합니다. 5배 넘게 벌어지면 신뢰도를 낮추고 숫자를 숨겨, 과신을 막습니다."],
];

// ── docx ──
const H1=t=>new Paragraph({heading:HeadingLevel.HEADING_1,spacing:{before:300,after:140},children:[new TextRun({text:t,bold:true,size:32,color:NAVY,font:F})]});
const H2=t=>new Paragraph({heading:HeadingLevel.HEADING_2,spacing:{before:240,after:80},children:[new TextRun({text:t,bold:true,size:25,color:GOLD,font:F})]});
const P=(t,o={})=>new Paragraph({spacing:{after:o.after??90},indent:o.ind?{left:o.ind}:undefined,children:[new TextRun({text:t,size:o.size??21,color:o.color??INK,italics:!!o.it,bold:!!o.b,font:F})]});
const term=(n,d,c=NAVY)=>new Paragraph({spacing:{after:100},children:[new TextRun({text:n+" : ",bold:true,size:20,color:c,font:F}),new TextRun({text:d,size:20,color:INK,font:F})]});

const k=[];
k.push(new Paragraph({alignment:AlignmentType.CENTER,spacing:{before:200,after:60},children:[new TextRun({text:"FINSIGHT 발표 스크립트 — V4",bold:true,size:40,color:NAVY,font:F})]}));
k.push(new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:40},children:[new TextRun({text:"부드럽고 쉬운 톤 · 비유 중심 · 슬라이드별 멘트 + AI 기술 매핑 + 기술 근거·Q&A",size:19,color:GRAY,font:F})]}));
k.push(new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:60},children:[new TextRun({text:"2026-06-19 · PPT V4와 1:1 대응",size:17,color:GRAY,font:F})]}));
k.push(P("읽는 법 : 🎙 = 실제로 말할 멘트(편하게 풀어 말하세요). (★ …)는 진행 메모 / 안 읽음. Part 2·3은 질문 대비용 참고 자료입니다.",{it:true,size:18,color:GRAY}));
k.push(new Paragraph({children:[new PageBreak()]}));

k.push(H1("Part 1.  슬라이드별 발표 멘트"));
SLIDES.forEach((sl,i)=>{
  k.push(H2(`${String(i+1).padStart(2,'0')}.  ${sl[0]}`));
  for(let j=1;j<sl.length;j++) k.push(P(sl[j]));
});

k.push(new Paragraph({children:[new PageBreak()]}));
k.push(H1("Part 2.  AI 기술 활용 총정리 + 화면 매핑  (참고)"));
k.push(P("비전공 심사위원이 ‘어떤 AI를 썼냐’ 물으면 이 표로 답하세요. 각 기술이 ‘무엇을 하고, 어느 화면에 쓰이는지’까지.",{it:true,size:18,color:GRAY}));
AI.forEach(([n,what,where])=>{
  k.push(new Paragraph({spacing:{after:30},children:[new TextRun({text:"▸ "+n,bold:true,size:20,color:NAVY,font:F})]}));
  k.push(P("무엇 — "+what,{ind:360,after:20,size:19}));
  k.push(P("화면 — "+where,{ind:360,after:110,size:19,color:GREEN}));
});
k.push(P("※ LangChain 미사용 — 검색·생성 파이프라인을 직접 구현해 동작을 통제합니다.",{it:true,size:18,color:GRAY}));

k.push(new Paragraph({children:[new PageBreak()]}));
k.push(H1("Part 3.  기술 스택 — 선택 근거 & 예상 Q&A  (참고)"));
k.push(H2("왜 이 기술을 골랐나"));
TECH.forEach(([n,d])=>k.push(term(n,d)));
k.push(H2("예상 Q&A"));
QA.forEach(([q,a])=>{
  k.push(new Paragraph({spacing:{after:20},children:[new TextRun({text:"Q. "+q,bold:true,size:20,color:NAVY,font:F})]}));
  k.push(P("A. "+a,{after:120,size:20}));
});

const doc=new Document({styles:{default:{document:{run:{font:F,size:21}}}},
  sections:[{properties:{page:{size:{width:11906,height:16838},margin:{top:1200,right:1200,bottom:1200,left:1200}}},children:k}]});
Packer.toBuffer(doc).then(b=>{fs.writeFileSync(process.argv[2],b);console.log("OK",b.length);});
