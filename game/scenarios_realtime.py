# backend/multi_game/rules/scenarios_realtime.py

SCENE_TEMPLATES = [
    {
        "id": "scene0",
        "index": 0,
        "roleMap": {
            "남동생": "brother",
            "누나": "sister",
            "호랑이": "tiger",
            "하늘신": "goddess",
        },
        "round": {
            "title": "어둠이 내린 산길",
            "choices": {
                "brother": [
                    {"id": "A", "text": "전력질주로 산길을 벗어난다", "appliedStat": "체력", "modifier": 0},
                    {"id": "B", "text": "바위 뒤로 숨는다", "appliedStat": "지혜", "modifier": 1},
                ],
                "sister": [
                    {"id": "C", "text": "조용히 발자국을 지운다", "appliedStat": "지혜", "modifier": 0},
                    {"id": "D", "text": "동생에게 신호를 보낸다", "appliedStat": "지혜", "modifier": 1},
                ],
                "tiger": [
                    {"id": "H", "text": "후각으로 냄새를 쫓는다", "appliedStat": "행운", "modifier": 0},
                    {"id": "J", "text": "소리를 질러 위협한다", "appliedStat": "지혜", "modifier": -1},
                ],
                "goddess": [
                    {"id": "V", "text": "아이들의 위치를 파악한다", "appliedStat": "지혜", "modifier": 2},
                    {"id": "W", "text": "산에 기적을 일으켜 호랑이를 막는다", "appliedStat": "행운", "modifier": 2},
                ],
            },
            "fragments": {
                "brother_A_SP": "남동생은 바람처럼 달 그림자 속으로 사라졌다.",
                "brother_A_S": "남동생은 숨을 헐떡이며 거리를 벌렸다.",
                "brother_A_F": "남동생은 발을 헛디뎌 넘어졌다.",
                "brother_A_SF": "남동생은 넘어져 다쳐 더 느려졌다.",
                "brother_B_SP": "남동생은 완벽히 숨었다.",
                "brother_B_S": "남동생은 간신히 몸을 숨겼다.",
                "brother_B_F": "남동생의 옷자락이 바람에 흔들렸다.",
                "brother_B_SF": "남동생은 소리를 내며 바위에 부딪혔다.",

                "sister_C_SP": "누나는 흔적을 완벽히 지웠다.",
                "sister_C_S": "누나는 발자국을 흐릿하게 만들었다.",
                "sister_C_F": "누나는 급해진 나머지 흙먼지를 남겼다.",
                "sister_C_SF": "누나는 진흙탕에 미끄러져 흔적을 잔뜩 남겼다.",
                "sister_D_SP": "누나는 눈빛으로 완벽한 신호를 보냈다.",
                "sister_D_S": "누나는 손짓으로 조심스레 신호를 보냈다.",
                "sister_D_F": "누나는 신호를 보내다 발소리를 냈다.",
                "sister_D_SF": "누나는 크게 외치고 말았다.",

                "tiger_H_SP": "호랑이는 냄새를 정교하게 좇았다.",
                "tiger_H_S": "호랑이는 방향을 가늠했다.",
                "tiger_H_F": "호랑이는 헛갈렸다.",
                "tiger_H_SF": "호랑이는 다른 동물의 냄새를 쫓았다.",
                "tiger_J_SP": "호랑이의 위협에 숲이 얼어붙었다.",
                "tiger_J_S": "호랑이의 포효가 메아리쳤다.",
                "tiger_J_F": "호랑이의 소리는 멀리 퍼지지 못했다.",
                "tiger_J_SF": "호랑이는 목이 쉰 듯 기침했다.",

                "goddess_V_SP": "하늘신은 아이들의 위치를 완벽히 파악했다.",
                "goddess_V_S": "하늘신은 아이들의 위치를 대략적으로 짐작했다.",
                "goddess_V_F": "하늘신은 아이들의 위치를 파악하지 못했다.",
                "goddess_V_SF": "하늘신은 혼란에 빠졌다.",
                "goddess_W_SP": "하늘신이 기적을 일으켜 산에 번개가 쳤다.",
                "goddess_W_S": "하늘신이 기적을 일으켜 호랑이 앞에 작은 벼락이 떨어졌다.",
                "goddess_W_F": "호랑이는 기적에 아랑곳하지 않았다.",
                "goddess_W_SF": "하늘신의 기도가 허공에 흩어졌다.",
            },
            "statChanges": {
                "brother_A_SP": {"체력": 1},
                "brother_A_SF": {"체력": -1},
                "brother_B_SP": {"지혜": 1},
                "brother_B_SF": {"지혜": -1},

                "sister_C_SP": {"지혜": 1},
                "sister_C_SF": {"지혜": -1},
                "sister_D_SP": {"지혜": 1},
                "sister_D_SF": {"지혜": -1},

                "tiger_H_SP": {"행운": 1},
                "tiger_H_SF": {"행운": -1},
                "tiger_J_SP": {"지혜": 1},
                "tiger_J_SF": {"지혜": -1},
                
                "goddess_V_SP": {"지혜": 2},
                "goddess_V_SF": {"지혜": -2},
                "goddess_W_SP": {"행운": 2},
                "goddess_W_SF": {"행운": -2},
            },
            "summaryByCombo": {
                "brother_A_F|sister_C_SP|tiger_H_S": 
                "호랑이는 방향을 잡았지만, 누나는 완벽히 흔적을 지웠고 남동생은 잠시 넘어졌다.",
            },
            "nextScene": {
                "routes": [
                    {"when": {"tiger": {"grade": ["SP", "S"]}}, "gotoIndex": 1},
                    {"when": {"sister": {"grade": ["SP"]}}, "gotoIndex": 2},
                ],
                "fallback": "+1",
            },
        },
    },
    {
        "id": "scene1",
        "index": 1,
        "roleMap": {
            "남동생": "brother",
            "누나": "sister",
            "호랑이": "tiger",
            "하늘신": "goddess",
        },
        "round": {
            "title": "숨 막히는 추격",
            "choices": {
                "brother": [
                    # '민첩' -> '체력'으로 변경
                    {"id": "E", "text": "나무 위로 올라간다", "appliedStat": "체력", "modifier": 0},
                    # '근력' -> '행운'으로 변경
                    {"id": "F", "text": "호랑이를 향해 돌을 던진다", "appliedStat": "행운", "modifier": 0},
                ],
                "sister": [
                    {"id": "G", "text": "연막탄을 터뜨린다", "appliedStat": "지혜", "modifier": 1},
                    # '매력' -> '지혜'로 변경
                    {"id": "I", "text": "호랑이를 다른 곳으로 유인한다", "appliedStat": "지혜", "modifier": 1},
                ],
                "tiger": [
                    {"id": "K", "text": "도망치는 아이들을 쫓는다", "appliedStat": "체력", "modifier": 0},
                    {"id": "L", "text": "주변을 살피며 매복한다", "appliedStat": "지혜", "modifier": 0},
                ],
                "goddess": [
                    {"id": "X", "text": "아이들을 숨겨줄 구름을 만든다", "appliedStat": "지혜", "modifier": 1},
                    {"id": "Y", "text": "호랑이를 방해할 바람을 일으킨다", "appliedStat": "행운", "modifier": 1},
                ],
            },
            "fragments": {
                "brother_E_SP": "남동생은 재빠르게 나무 위로 날아올랐다.",
                "brother_E_S": "남동생은 나무 위로 간신히 몸을 숨겼다.",
                "brother_E_F": "남동생은 가지를 놓쳐 바닥으로 굴러떨어졌다.",
                "brother_E_SF": "남동생은 나무에 부딪혀 정신을 잃었다.",
                "brother_F_SP": "남동생이 던진 돌이 호랑이의 머리를 정통으로 맞혔다.",
                "brother_F_S": "남동생이 던진 돌이 호랑이의 시야를 가렸다.",
                "brother_F_F": "돌은 엉뚱한 곳에 떨어졌다.",
                "brother_F_SF": "돌은 나뭇가지에 걸려 큰 소리를 냈다.",
                
                "sister_G_SP": "누나가 터뜨린 연막탄이 짙은 안개를 만들어냈다.",
                "sister_G_S": "누나는 작은 폭죽을 터뜨려 호랑이의 주의를 끌었다.",
                "sister_G_F": "연막탄이 터지지 않았다.",
                "sister_G_SF": "연막탄에서 연기가 새어나와 누나를 당황시켰다.",
                "sister_I_SP": "누나는 호랑이를 완벽하게 다른 곳으로 유인하는 데 성공했다.",
                "sister_I_S": "누나는 호랑이를 잠시 혼란에 빠뜨렸다.",
                "sister_I_F": "호랑이는 누나의 꾀를 눈치챘다.",
                "sister_I_SF": "호랑이는 오히려 더 맹렬히 달려들었다.",
                
                "tiger_K_SP": "호랑이는 아이들을 맹렬하게 추격했다.",
                "tiger_K_S": "호랑이는 아이들 뒤를 쫓으며 거리를 좁혔다.",
                "tiger_K_F": "호랑이는 넘어졌고, 아이들과의 거리가 벌어졌다.",
                "tiger_K_SF": "호랑이는 풀숲에 발이 걸려 더 이상 쫓지 못했다.",
                "tiger_L_SP": "호랑이는 주변을 살피고 완벽하게 매복했다.",
                "tiger_L_S": "호랑이는 바위 뒤에 몸을 숨겼다.",
                "tiger_L_F": "호랑이의 꼬리가 보여 아이들에게 들켰다.",
                "tiger_L_SF": "호랑이가 매복한 장소에 다른 동물들이 나타났다.",
                
                "goddess_X_SP": "하늘신이 만든 구름이 아이들을 완전히 덮었다.",
                "goddess_X_S": "하늘신의 구름이 아이들을 흐릿하게 만들었다.",
                "goddess_X_F": "구름은 곧바로 흩어졌다.",
                "goddess_X_SF": "구름 때문에 오히려 아이들의 위치가 노출됐다.",
                "goddess_Y_SP": "하늘신이 일으킨 바람이 호랑이의 코를 막았다.",
                "goddess_Y_S": "하늘신이 일으킨 바람이 호랑이의 주의를 분산시켰다.",
                "goddess_Y_F": "바람이 너무 약해 아무 효과가 없었다.",
                "goddess_Y_SF": "바람이 반대 방향으로 불어 호랑이에게 도움을 주었다.",
            },
            "statChanges": {
                # '민첩' -> '체력' 변경
                "brother_E_SP": {"체력": 1},
                "brother_E_SF": {"체력": -1},
                # '근력' -> '행운' 변경
                "brother_F_SP": {"행운": 1},
                "brother_F_SF": {"행운": -1},

                "sister_G_SP": {"지혜": 1},
                "sister_G_SF": {"지혜": -1},
                # '매력' -> '지혜' 변경
                "sister_I_SP": {"지혜": 1},
                "sister_I_SF": {"지혜": -1},

                "tiger_K_SP": {"체력": 1},
                "tiger_K_SF": {"체력": -1},
                "tiger_L_SP": {"지혜": 1},
                "tiger_L_SF": {"지혜": -1},

                "goddess_X_SP": {"지혜": 2},
                "goddess_X_SF": {"지혜": -2},
                "goddess_Y_SP": {"행운": 2},
                "goddess_Y_SF": {"행운": -2},
            },
            "summaryByCombo": {
                "brother_E_S|sister_I_S|tiger_K_S": "남동생과 누나가 간신히 몸을 숨기고 호랑이의 주의를 분산시켰지만, 호랑이는 여전히 추격을 멈추지 않았다.",
            },
            "nextScene": {
                "routes": [
                    {"when": {"tiger": {"grade": ["SP", "S"]}}, "gotoIndex": 2},
                    {"when": {"sister": {"grade": ["SP"]}}, "gotoIndex": 3},
                ],
                "fallback": "+1",
            },
        },
    },
    {
        "id": "scene2",
        "index": 2,
        "roleMap": {
            "남동생": "brother",
            "누나": "sister",
            "호랑이": "tiger",
            "하늘신": "goddess",
        },
        "round": {
            "title": "운명의 결전",
            "choices": {
                "brother": [
                    # '매력' -> '지혜'로 변경
                    {"id": "M", "text": "큰 소리로 호랑이를 위협한다", "appliedStat": "지혜", "modifier": -1},
                    # '근력' -> '체력'으로 변경
                    {"id": "N", "text": "나무 막대기를 찾아 방어한다", "appliedStat": "체력", "modifier": 1},
                ],
                "sister": [
                    {"id": "O", "text": "마을을 향해 달려간다", "appliedStat": "체력", "modifier": 0},
                    {"id": "P", "text": "가지고 있던 콩 주머니를 던진다", "appliedStat": "행운", "modifier": 0},
                ],
                "tiger": [
                    {"id": "Q", "text": "아이들을 향해 포효한다", "appliedStat": "지혜", "modifier": 0},
                    # '민첩' -> '체력'으로 변경
                    {"id": "R", "text": "경로를 차단하고 길목을 지킨다", "appliedStat": "체력", "modifier": 1},
                ],
                "goddess": [
                    {"id": "Z", "text": "아이들을 하늘로 끌어올린다", "appliedStat": "지혜", "modifier": 2},
                    {"id": "AA", "text": "호랑이에게 벌을 내린다", "appliedStat": "행운", "modifier": 3},
                ],
            },
            "fragments": {
                "brother_M_SP": "남동생의 우렁찬 목소리가 호랑이를 멈칫하게 했다.",
                "brother_M_S": "남동생의 외침에 호랑이가 잠시 주춤했다.",
                "brother_M_F": "목소리가 너무 작아 호랑이가 듣지 못했다.",
                "brother_M_SF": "남동생은 목소리만 내고 곧바로 겁에 질렸다.",
                "brother_N_SP": "남동생은 호랑이를 압도할 튼튼한 나무 막대기를 찾았다.",
                "brother_N_S": "남동생은 호신용으로 쓸 막대기를 손에 쥐었다.",
                "brother_N_F": "막대기는 쉽게 부러져 쓸모가 없었다.",
                "brother_N_SF": "나무를 찾다가 넘어져 호랑이에게 공격당했다.",

                "sister_O_SP": "누나는 엄청난 속도로 마을로 달려갔다.",
                "sister_O_S": "누나는 전력으로 뛰었지만 호랑이의 발소리가 등 뒤에서 들려왔다.",
                "sister_O_F": "누나는 지쳐서 더 이상 뛸 수 없었다.",
                "sister_O_SF": "누나는 헛발을 딛고 넘어져 큰 부상을 입었다.",
                "sister_P_SP": "누나가 던진 콩이 호랑이의 눈에 정확히 들어갔다.",
                "sister_P_S": "콩 주머니가 호랑이의 시야를 잠시 가렸다.",
                "sister_P_F": "콩 주머니는 허공에 흩뿌려졌다.",
                "sister_P_SF": "누나가 던진 콩이 호랑이를 화나게 만들었다.",

                "tiger_Q_SP": "호랑이의 포효에 아이들은 얼어붙었다.",
                "tiger_Q_S": "호랑이의 포효가 아이들을 위협했다.",
                "tiger_Q_F": "호랑이의 포효는 공허한 소리였다.",
                "tiger_Q_SF": "호랑이의 목이 쉬어 소리가 나오지 않았다.",
                "tiger_R_SP": "호랑이는 완벽한 길목을 찾아 아이들의 도주로를 차단했다.",
                "tiger_R_S": "호랑이가 아이들 앞길을 막아섰다.",
                "tiger_R_F": "호랑이는 예상치 못한 곳에서 나타났다.",
                "tiger_R_SF": "호랑이가 길을 막았지만, 다른 곳으로 우회하는 길을 열어주었다.",
                
                "goddess_Z_SP": "하늘신은 아이들을 하늘로 끌어올려 안전하게 구했다.",
                "goddess_Z_S": "하늘신이 아이들의 몸을 공중으로 살짝 띄웠다.",
                "goddess_Z_F": "아이들은 땅에 발이 붙어 있었다.",
                "goddess_Z_SF": "하늘신은 아이들을 들어 올리는 데 실패했다.",
                "goddess_AA_SP": "호랑이는 하늘신의 벌을 받고 꼼짝 못하게 되었다.",
                "goddess_AA_S": "호랑이는 벌을 받고 잠시 고통스러워했다.",
                "goddess_AA_F": "벌은 호랑이에게 아무런 영향을 주지 못했다.",
                "goddess_AA_SF": "벌은 빗나가 호랑이에게 아무런 피해를 주지 못했다.",
            },
            "statChanges": {
                # '매력' -> '지혜' 변경
                "brother_M_SP": {"지혜": 1},
                "brother_M_SF": {"지혜": -1},
                # '근력' -> '체력' 변경
                "brother_N_SP": {"체력": 1},
                "brother_N_SF": {"체력": -1},
                
                "sister_O_SP": {"체력": 1},
                "sister_O_SF": {"체력": -1},
                "sister_P_SP": {"행운": 1},
                "sister_P_SF": {"행운": -1},

                "tiger_Q_SP": {"지혜": 1},
                "tiger_Q_SF": {"지혜": -1},
                # '민첩' -> '체력' 변경
                "tiger_R_SP": {"체력": 1},
                "tiger_R_SF": {"체력": -1},
                
                "goddess_Z_SP": {"지혜": 2},
                "goddess_Z_SF": {"지혜": -2},
                "goddess_AA_SP": {"행운": 3},
                "goddess_AA_SF": {"행운": -3},
            },
            "summaryByCombo": {
                "brother_N_S|sister_P_S|tiger_R_S": "남동생은 막대기를 쥐었고, 누나의 콩이 호랑이의 시야를 가렸지만, 호랑이는 길목을 막아섰다.",
            },
            "nextScene": {
                "routes": [],
                "fallback": "end",
            },
        },
    },
]

def get_scene_template(index: int):
    for tpl in SCENE_TEMPLATES:
        if tpl["index"] == index:
            return tpl
    return None