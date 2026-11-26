-- 5차(2026-11-26): 장보기픽 비식품 분류 보강(에그팬·비데·압력패킹·쿠쿠 등), 가격 없는 링크·문구·UI 글자 제외
-- 분류 함수(아래 내용은 config/category_rules.json 최신본으로 생성)
create or replace function public.classify_product(p_name text, p_prefer text default null) returns text
language plpgsql immutable set search_path = public as $$
-- 자동 생성: scripts/gen_category_sql.py (규칙 원본 config/category_rules.json). 손으로 고치지 말 것.
declare
  sp text[] := array['아이스크림|생크림|휘핑크림|크림치즈|크림빵|슈크림|크림파스타|크림스프|토마토소스','헤어밴드|헤어핀|헤어집게|헤어끈|오리털|거위털','바디필로우','커피머신|커피메이커|밥솥|냉동고|전기밥솥|김치냉장고'];
  sc text[] := array['식품','패션','가구·인테리어','가전·디지털'];
  cs text[] := array['식품','뷰티','생활·주방','패션','가전·디지털','가구·인테리어','유아동','스포츠·레저','반려동물','도서·취미','명품'];
  ps text[] := array['수산|굴비|생굴|통영굴|석화|고등어|생선|갈치|조기|명태|황태|오징어|문어|낙지|쭈꾸미|주꾸미|새우|대게|킹크랩|꽃게|전복|가리비|홍합|연어|참치|장어|멸치|조미김|김자반|도시락김|파래김|김세트|미역|다시마|한우|한돈|소고기|쇠고기|돼지고기|삼겹|목살|갈비|불고기|닭가슴살|닭고기|치킨|계란|달걀|우유|요거트|요구르트|치즈|버터|두유|만두|햄(?!스터|버거)|소시지|비엔나|베이컨|스팸|라면|국수|파스타|우동|냉면|쌀\y|현미|잡곡|햇반|즉석밥|볶음밥|비빔밥|김치|반찬|과일|감귤|귤|사과|딸기|포도|샤인머스캣|바나나|망고|키위|오렌지|레몬|자몽|토마토|채소|야채|샐러드|양파|감자|고구마|버섯|소스|케찹|케첩|마요네즈|된장|고추장|간장|식용유|올리브유|참기름|들기름|원두|커피|녹차|홍차|음료|생수|탄산수|주스|콜라|사이다|과자|스낵|초콜릿|쿠키|빵|베이글|떡|견과|아몬드|호두|꿀|잼|시리얼|그래놀라|아이스크림|홍삼|건강기능|영양제|유산균|프로바이오틱스|비타민|오메가|루테인|단백질|프로틴|밀키트|간편식|떡볶이|피자|돈까스|돈가스|함박|미트볼|육포|어묵|두부|곶감|군밤|밤\s*\d|식품|푸드|먹거리|정육|축산|신선|진액|흑염소|공력환|팥죽|전복죽|호박죽|앙금|데니쉬|바게트|생지|슈톨렌|맥주|막걸리|와인|소주|요리술|식초|고춧가루|명란|동태|육개장|곰탕|마라탕|탕면|짜장|중화면|스파게티면|칼국수|특란|대란|구운란|등급란|양상추|당귀|산양유|단백질드링크|연어|육즙|교자|후랑크|리챔|참치|볶음김치|그릭|비첸향|육포|jerky|슬라이스\s*포크|오뚜기밥|100밥|솥밥|흑미밥|오곡밥|현미밥|곤약밥|컵밥|밥\s*\d|딤섬|창펀|샤오롱바오|오리|훈제|스테이크|토마호크|광어|방어|대광어|회\s*\d|젓갈|황석어젓|명란젓|순대|설렁탕|삼계탕|백숙|해장국|북엇국|우거지국|간편국|찌개|수프|스프(?!레이)|누룽지|올리브오일|발사믹|펜네|링귀니|스파게티|푸질리|카펠리니|파팔레|리가토니|라자냐|오트밀|곤약|누들|젤리|구미(?!시)|크래커|나쵸|케챂|스프레드|땅콩|티라미수|케이크|샌드위치|치아바타|사워도우|도라지|청국장|배추|김칫속|절임|단감|무화과|파인애플|브로콜리|우렁|꼬막|골뱅이|번데기|스위트콘|황도|생강|천일염|후추|육수|다시팩|산양삼|녹즙|블루베리즙|흑삼|옥타코사놀|효소|차전자피|원유|유정란|반숙란|너겟|돈카츠|부어스트|폭립|잠봉|탕수육|막창|곱창김|만전김|김밥용|어린이김|두유|께사디야|칠리|아보카도유|해쉬브라운|오란다|트러플\s*크래커|말차|초코|간식세트|약청|콩탕|부추|먹는|분유|이유식|떡국|가래떡|홍삼정|즙\s*\d|녹즙|양갱|두부|묵\s*\d|들깨|깨\s*\d|모밀|메밀|곡물|밀크티|벤딩밀크|테이토|순살|닭강정','앰플|세럼|에센스|토너|(?<!램)(?<!양)(?<!가죽)스킨(?!십)|로션|크림|선케어|자외선|쿠션|파운데이션|컨실러|립스틱|립밤|틴트|마스카라|아이섀도|블러셔|마스크팩|시트마스크|(토너|글로우|각질|진정|필링|화장)\s*패드|패드\s*\d+\s*매|클렌징|클렌저|필링|미스트|샴푸|린스|트리트먼트|컨디셔너|헤어|바디\s*워시|바디로션|핸드크림|향수|퍼퓸|데오드란트|네일|화장품|코스메틱|뷰티|스킨케어|레티놀|pdrn|히알루론|시카|멜라토닝|선크림|선스틱|팩클렌저|입욕제|배쓰\s*밤|샤워\s*젤|염색제|비비크림|블러셔|토닝|필링젤|핸드\s*&\s*립|립\s*세트|왁스|선패치|프로폴리스\s*스프레이(?!.*먹)','세제|섬유유연제|유연제|휴지|화장지|물티슈|키친타올|키친타월|칫솔|치약|가글|구강|수건|타월|행주|수세미|프라이팬|냄비|도마|밀폐용기|텀블러|머그|종이컵|접시|그릇|수납|정리함|청소|걸레|빨래|건조대|방향제|탈취|살충|비누|핸드\s*워시|생리대|위생|주방|욕실|생활용품|생필품|캔들|디퓨저|믹싱볼|거품기|국자|뒤집개|필러|궁중팬|소테|밴드\s*\d+매|구연산|얼음|리필|에그팬|압력\s*패킹|고무\s*패킹|실리콘\s*패킹','양말|티셔츠|맨투맨|후디|후드|셔츠|블라우스|팬츠|바지|슬랙스|스커트|원피스|재킷|자켓|점퍼|패딩|코트|니트|가디건|카디건|조끼|레깅스|속옷|팬티|브라(?=\s|$|탑|\d|세트|\))|브래지어|내의|잠옷|파자마|모자|비니|장갑|목도리|머플러|가방|백팩|지갑|신발|운동화|스니커즈|부츠|슬리퍼|샌들|레그워머|헤어밴드|의류|패션|아우터|데님|언더웨어|덕다운|구스다운|다운\s*(점퍼|재킷|자켓|베스트|패딩)|플리스|후리스|스웨트|sweatshirt|knit|coat|jacket|pants|skirt|boots|sneakers|shirt|\ytee\y|cardigan|hoodie|scarf|muffler|\ycap\y|beanie|dress|\yvest\y|드로즈|브라탑|트렁크|청바지|슬립온|로퍼|첼시|부티|숄|넥워머|바라클라바|트레이닝|조거|수영복|swimsuit|트렌치|블레이저|토트|메신저백|크로스백|벨트|tote|backpack|\ybag\y|귀걸이|목걸이|반지|팔찌|타이즈|홈웨어|가운|램스킨|헝가리구스|구스\s*다운','가전|노트북|모니터|스마트폰|갤럭시|아이폰|태블릿|청소기|냉장고|세탁기|에어컨|건조기|이어폰|헤드폰|스피커|카메라|공기청정기|가습기|제습기|전기요|전기장판|히터|난로|에어프라이어|전자레인지|밥솥|커피머신|믹서기|블렌더|드라이기|면도기|tv\y|티비|pc\y|키보드|마우스|충전기|보조배터리|led\s*tv|qled|oled|mini\s*led|실링팬|선풍기|전기그릴|와이드\s*그릴|비데|정수기|전기\s*포트|인덕션\s*레인지|식기세척기|쿠쿠|cuckoo|트윈\s*프레셔|압력\s*솥|하이라이트|전기\s*레인지|인덕션(?!\s*겸용)','가구|인테리어|침대|매트리스|소파|책상|의자|테이블|선반|조명|커튼|러그|카페트|이불|베개|침구|액자|사이드보드|트롤리|붙박이장|옷장|식탁|블랭킷|sofa|암체어|스탠드|플로어|카펫|통통패드|매트리스패드|침대패드|토퍼|가제보|파라솔|정원용\s*우산','유아|아동|키즈|kids|베이비|출산|육아|기저귀|장난감|완구|젖병','스포츠|아웃도어|골프|러닝|캠핑|텐트|등산|피트니스|요가|스키|자전거|헬스|덤벨','반려|(?<!카)펫|강아지|고양이|사료|간식(?=.*(강아지|고양이|반려))|캣(?!츠)|(?<!핫)도그|배변패드|벤토나이트|모래(?=.*(고양이|캣))|고양이\s*모래','도서|문구|다이어리|플래너|필기구|볼펜|만년필|노트(?!북)|스티커|마스킹테이프|음반|악기|퍼즐|레고|\[외서\]|\[도서\]|스티커북|북커버|양서','명품|럭셔리|구찌|샤넬|프라다|버버리|몽클레르|루이비통|에르메스'];
  t text := lower(coalesce(p_name, ''));
  sc_score int[] := array_fill(0, array[array_length(cs, 1)]);
  n int; i int; j int; best int := 0; besti int := 0; pidx int;
begin
  if t = '' then return null; end if;
  for i in 1 .. array_length(sp, 1) loop
    select count(*) into n from regexp_matches(t, sp[i], 'gi');
    if n > 0 then
      j := array_position(cs, sc[i]);
      if j is not null then sc_score[j] := sc_score[j] + n; end if;
      t := regexp_replace(t, sp[i], ' ', 'gi');
    end if;
  end loop;
  for i in 1 .. array_length(cs, 1) loop
    select count(*) into n from regexp_matches(t, ps[i], 'gi');
    sc_score[i] := sc_score[i] + n;
  end loop;
  for i in 1 .. array_length(cs, 1) loop
    if sc_score[i] > best then best := sc_score[i]; besti := i; end if;
  end loop;
  if besti = 0 then return null; end if;
  pidx := array_position(cs, p_prefer);
  if pidx is not null and sc_score[pidx] = best then return p_prefer; end if;   -- 동점이면 기획전 제목 분류 우선
  return cs[besti];
end $$;
update public.promotion_items i set category = public.classify_product(i.name, public.classify_product(p.title))
from public.promotions p
where p.id = i.promotion_id and public.classify_product(i.name, public.classify_product(p.title)) is not null
  and i.category is distinct from public.classify_product(i.name, public.classify_product(p.title));


do $$
declare d text := pg_get_viewdef('public.v_promotions'::regclass, true);
  f text := ' i2.category = ''식품'' AND i2.price IS NOT NULL AND i2.name !~* ''^(장바구니(\s*담기)?|재입고(\s*(신청|알림))?)$'' AND i2.name !~ ''\*{2,}\s*고객님'' AND';
begin
  d := replace(d, 'WHERE i2.promotion_id = p.id AND', 'WHERE i2.promotion_id = p.id AND' || f);
  d := replace(d, 'WHERE i.promotion_id = p.id AND', 'WHERE i.promotion_id = p.id AND' || replace(f, 'i2.', 'i.'));
  d := replace(d, 'WHERE lr.last_good_run IS NOT NULL', 'WHERE (COALESCE(agg.item_count, 0) > 0 OR p.category = ''식품'') AND lr.last_good_run IS NOT NULL');
  execute 'create or replace view public.v_promotions_food with (security_invoker = true) as ' || d;
end $$;
grant select on public.v_promotions_food to anon, authenticated;

do $$
declare d text := pg_get_functiondef('private.refresh_picks_for(text,text[],int,int,int,numeric,int)'::regprocedure);
begin
  if position('재입고' in d) = 0 then
    d := replace(d, 'and (v <> ''food'' or i.category = ''식품'')', 'and (v <> ''food'' or i.category = ''식품'') and i.name !~* ''^(장바구니(\s*담기)?|재입고(\s*(신청|알림))?)$'' and i.name !~ ''\*{2,}\s*고객님''');
    execute d;
  end if;
end $$;

-- 수정: API(PostgREST)는 WHERE 없는 DELETE를 막는다 → 추천 계산('all')이 400으로 실패하던 원인
do $$
declare d text := pg_get_functiondef('private.refresh_source_defaults()'::regprocedure);
begin
  d := regexp_replace(d, 'delete from public\.source_default_category\s*;', 'delete from public.source_default_category where true;');
  execute d;
end $$;
