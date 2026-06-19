const fs=require('fs');
const {Document,Packer,Paragraph,TextRun,HeadingLevel,AlignmentType,PageBreak}=require('docx');
const F="맑은 고딕",NAVY="0E2742",GOLD="B5872B",INK="1A2430",GRAY="5A6573",GREEN="1A6E47";

const SECS=[
["도입 — 관리자 페이지란?","~25s",[
 "🎙 “지금까지가 사용자 화면이었다면, 관리자 페이지는 저희가 그 화면을 어떻게 책임지는지 — 데이터가 진짜인지 스스로 감시하고 검증하는 ‘내부 통제판’입니다. 비밀번호로 보호되고, 모든 수치는 누르는 순간 실제 DB를 조회한 실측값이며, 없으면 가짜 대신 ‘없음’으로 둡니다.”",
 "🎙 (4탭 한 줄 개요) “네 탭으로 되어 있습니다 — ① 기업분석 운영(상태 감시), ② 기업분석 검증(데이터를 원본과 대조), ③ 밸류에이션 운영(재료·출처 공개), ④ 밸류에이션 테스트(직접 눌러 점검). 하나씩 핵심만 보겠습니다.”"]],
["탭 ① 기업분석 운영 — ‘서비스 건강검진표’","~45s",[
 "🎙 “첫째, 운영 탭입니다. 핵심은 ‘기능 모듈 현황’ — 각 기능이 DART·KRX 같은 공식 원천에서 화면까지 어떻게 흐르고 지금 정상인지를 한 줄로 보여줍니다. 그 아래 커버리지로 전 종목 보유율을, DB 현황으로 16개 테이블 행수를 보고요.”",
 "🎙 “데이터 신선도에서는 주가가 매 거래일 16시에 자동 갱신되는 걸 확인하고, 챗봇 상태와 AWS 비용까지 한 화면에서 봅니다. 즉, 어떤 데이터가 어디서 와서 지금 정상인지를 매일 5분이면 점검하는 곳입니다.”"]],
["탭 ② 기업분석 검증 — ‘맞다를 버튼으로 증명’ (★핵심)","~65s",[
 "🎙 “둘째, 검증 탭이 저희가 가장 자신 있는 부분입니다. 데이터가 ‘있다’를 넘어 ‘맞다’를 버튼으로 증명합니다.”",
 "🎙 (실연) “먼저 내부 정합성 — 재무 파트를 고르고 검증을 누르면, ‘자산 = 부채 + 자본’ 회계 항등식을 전 종목 검사해 (클릭) 오류율 0%를 즉석에서 보여드립니다.”",
 "🎙 “그리고 DART 원문 대조 — 저희 요약 재무를 금융감독원 공시 원본과 맞대어, 누구나 원본으로 팩트체크할 수 있게 했습니다. AI가 쓴 히스토리 브리핑도 4단계로 자동 채점해 평균 77점으로 관리하고요. 한마디로, 말이 아니라 즉석에서 증명하는 겁니다.”"]],
["탭 ③ 밸류에이션 운영 — ‘투명성 상태판’","~40s",[
 "🎙 “셋째, 밸류 운영 탭은 적정주가를 만든 재료와 출처를 숨김없이 공개하는 곳입니다. 평가에 쓴 데이터가 며칠 자인지 — 평가일·금리·시가총액 세 날짜가 서로 가까운지가 핵심이고, 출처는 DART·거래소·한국은행 등 여덟 곳 전부 공식입니다.”",
 "🎙 “가장 강조하고 싶은 건 ‘AI 하네스’ — AI가 거짓을 못 짓게 막는 네 장치입니다. 없으면 비우고, 찾기만 맡기고, 모든 답에 출처를 붙이고, 확신이 약하면 숨깁니다.”"]],
["탭 ④ 밸류에이션 테스트 — ‘직접 눌러 점검’","~40s",[
 "🎙 “넷째, 테스트 탭은 말이 아니라 직접 눌러 확인하는 점검판입니다. 위 신호등 셋으로 백엔드·챗봇·프론트가 살아있는지 보고요.”",
 "🎙 “밸류 QA에서 종목을 넣고 검증하면 적정주가·WACC·신뢰도 등급과, 꼭 있어야 할 다섯 항목이 다 체크되는지 보여줍니다. 아직 평가 안 한 종목은 가짜 대신 ‘준비 중’으로 정직하게 나오고요. 챗봇 QA는 답에 DART 출처가 붙는지 확인합니다.”"]],
["마무리","~15s",[
 "🎙 “정리하면 — 운영으로 감시하고, 검증으로 원본과 대조하고, 밸류로 AI의 거짓을 막습니다. 저희가 끝까지 지킨 한 문장으로 마치겠습니다 — ‘추정하지 않습니다, 출처로 말합니다.’”"]],
];

const TIP=[
 "1) /admin 접속(로그인까지 미리) → “내부 통제판입니다” + NO-MOCK 한 줄.",
 "2) ① 운영 탭: 기능 모듈 현황 → 커버리지 → 신선도 위→아래 드래그.",
 "3) ② 검증 탭: 재무 파트 선택 → [샘플 검증] 실제 클릭(오류율 0%) → [DART 원문 대조] 한 번.",
 "4) ③ 밸류 운영: ‘AI 하네스’ 강조.  5) ④ 밸류 테스트: 신호등 → 밸류 QA 종목 1개 검증 → ‘준비 중=정직’.",
 "6) 클로징: “추정하지 않습니다, 출처로 말합니다.”",
];

const H1=t=>new Paragraph({heading:HeadingLevel.HEADING_1,spacing:{before:280,after:120},children:[new TextRun({text:t,bold:true,size:32,color:NAVY,font:F})]});
const H2=(t,tm)=>new Paragraph({heading:HeadingLevel.HEADING_2,spacing:{before:220,after:70},children:[new TextRun({text:t,bold:true,size:23,color:GOLD,font:F}),...(tm?[new TextRun({text:"   "+tm,size:16,color:GRAY,font:F})]:[])]});
const P=(t,o={})=>new Paragraph({spacing:{after:o.after??90},children:[new TextRun({text:t,size:o.size??21,color:o.color??INK,italics:!!o.it,font:F})]});

const k=[];
k.push(new Paragraph({alignment:AlignmentType.CENTER,spacing:{before:200,after:50},children:[new TextRun({text:"FINSIGHT 관리자 페이지 — 시연 스크립트 (약 4분)",bold:true,size:36,color:NAVY,font:F})]}));
k.push(new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:40},children:[new TextRun({text:"4탭 전체 개요 → 탭별 핵심 기능 · 라이브 /admin 시연용 · 2026-06-20",size:18,color:GRAY,font:F})]}));
k.push(P("읽는 법 : 🎙 = 말할 멘트. (클릭)/(실연)은 버튼 동작 신호. 모든 박스를 설명하지 않고 핵심만. ★검증 탭에 시간을 쓰세요(데모 하이라이트).",{it:true,size:18,color:GRAY,after:60}));
k.push(new Paragraph({children:[new PageBreak()]}));

SECS.forEach(([t,tm,lines])=>{ k.push(H2(t,tm)); lines.forEach(l=>k.push(P(l))); });

k.push(new Paragraph({children:[new PageBreak()]}));
k.push(H1("시연 동선 (약 4분)"));
TIP.forEach(s=>k.push(P(s,{size:20})));
k.push(P("※ 전부 실제 화면·실측값(NO-MOCK). 검증 탭은 AWS 라이브에서 작동 확인됨(재무 항등식 오류율 0%). DART 원문 대조는 일치율을 ‘과정’으로 보여주고, 숫자 강조는 재무 항등식 0%로.",{it:true,size:18,color:GRAY}));

const doc=new Document({styles:{default:{document:{run:{font:F,size:21}}}},
  sections:[{properties:{page:{size:{width:11906,height:16838},margin:{top:1200,right:1200,bottom:1200,left:1200}}},children:k}]});
Packer.toBuffer(doc).then(b=>{fs.writeFileSync(process.argv[2],b);console.log("OK",b.length);});
