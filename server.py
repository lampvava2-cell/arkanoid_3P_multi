import asyncio
import json
import math
import random
import websockets

WIDTH = 400
HEIGHT = 600

# 버전 타이틀 (클라이언트로 전달)
VERSION_TITLE = "속도개선버전3 (Stage & Lobby Update)"

# 슬롯 상태: {"bottom": ws or "BOT", "left": ws or "BOT", "right": ws or "BOT"}
SLOTS = {"bottom": "BOT", "left": "BOT", "right": "BOT"}
CONNECTED_CLIENTS = {}  # ws: {"role": None, "ready": False}

game_started = False
current_stage = 1
TOTAL_STAGES = 3

paddle_positions = {
    "bottom": WIDTH / 2,
    "left": HEIGHT / 2,
    "right": HEIGHT / 2
}

BALL_BASE_SPEED = 6.2
ball = {
    "x": WIDTH / 2,
    "y": HEIGHT / 2 + 100,
    "vx": 4.5,
    "vy": -4.5,
    "radius": 8
}

bricks = []

def generate_stage(stage_num):
    new_bricks = []
    brick_id = 0
    if stage_num == 1:
        # 스테이지 1: 5x5 기본 사각형
        rows, cols = 5, 5
        start_x = (WIDTH - (cols * 36)) / 2 + 3
        start_y = (HEIGHT - (rows * 22)) / 2 - 20
        for r in range(rows):
            for c in range(cols):
                new_bricks.append({"id": brick_id, "x": start_x + c * 36, "y": start_y + r * 22, "w": 30, "h": 14, "alive": True})
                brick_id += 1
    elif stage_num == 2:
        # 스테이지 2: 십자형 클러스터
        for r in range(7):
            for c in range(7):
                if r == 3 or c == 3 or (abs(r - 3) + abs(c - 3) <= 2):
                    new_bricks.append({"id": brick_id, "x": 75 + c * 36, "y": 170 + r * 22, "w": 30, "h": 14, "alive": True})
                    brick_id += 1
    else:
        # 스테이지 3: 다이아몬드 & 요새
        for r in range(6):
            for c in range(6):
                if r == 0 or r == 5 or c == 0 or c == 5 or (r in [2,3] and c in [2,3]):
                    new_bricks.append({"id": brick_id, "x": 90 + c * 36, "y": 180 + r * 22, "w": 30, "h": 14, "alive": True})
                    brick_id += 1
    return new_bricks

def reset_ball():
    global ball
    ball["x"] = WIDTH / 2
    ball["y"] = HEIGHT / 2 + 80
    angle = random.uniform(-0.7, 0.7)
    ball["vx"] = BALL_BASE_SPEED * math.sin(angle)
    ball["vy"] = -abs(BALL_BASE_SPEED * math.cos(angle))

bricks = generate_stage(current_stage)

def update_ai():
    ai_speed = 6.0
    if SLOTS["bottom"] == "BOT":
        tx = ball["x"]
        cx = paddle_positions["bottom"]
        paddle_positions["bottom"] += max(-ai_speed, min(ai_speed, tx - cx))
        paddle_positions["bottom"] = max(35, min(WIDTH - 35, paddle_positions["bottom"]))

    if SLOTS["left"] == "BOT":
        ty = ball["y"]
        cy = paddle_positions["left"]
        paddle_positions["left"] += max(-ai_speed, min(ai_speed, ty - cy))
        paddle_positions["left"] = max(35, min(HEIGHT - 35, paddle_positions["left"]))

    if SLOTS["right"] == "BOT":
        ty = ball["y"]
        cy = paddle_positions["right"]
        paddle_positions["right"] += max(-ai_speed, min(ai_speed, ty - cy))
        paddle_positions["right"] = max(35, min(HEIGHT - 35, paddle_positions["right"]))

async def broadcast_lobby():
    slots_info = {}
    for role, occ in SLOTS.items():
        if occ == "BOT":
            slots_info[role] = "BOT"
        else:
            slots_info[role] = "USER"
    payload = json.dumps({
        "type": "lobby_state",
        "title": VERSION_TITLE,
        "slots": slots_info,
        "game_started": game_started,
        "stage": current_stage
    })
    for ws in list(CONNECTED_CLIENTS.keys()):
        try:
            await ws.send(payload)
        except:
            pass

async def game_loop():
    global game_started, current_stage, bricks, ball
    P_LEN = 65

    while True:
        if game_started:
            update_ai()

            # 터널링(벽돌 관통) 방지: 2회 서브스텝 물리 검사
            sub_steps = 2
            step_vx = ball["vx"] / sub_steps
            step_vy = ball["vy"] / sub_steps

            for _ in range(sub_steps):
                ball["x"] += step_vx
                ball["y"] += step_vy

                # 상단 벽 반사
                if ball["y"] - ball["radius"] <= 10:
                    ball["y"] = 10 + ball["radius"]
                    ball["vy"] = abs(ball["vy"])
                    step_vy = abs(step_vy)

                # 하단 패들 충돌
                if ball["y"] + ball["radius"] >= HEIGHT - 22:
                    pad_x = paddle_positions["bottom"]
                    if pad_x - P_LEN / 2 <= ball["x"] <= pad_x + P_LEN / 2:
                        ball["vy"] = -abs(ball["vy"])
                        step_vy = -abs(step_vy)
                        offset = (ball["x"] - pad_x) / (P_LEN / 2)
                        ball["vx"] = offset * 5.5
                        step_vx = ball["vx"] / sub_steps
                    elif ball["y"] > HEIGHT + 30:
                        reset_ball()
                        break

                # 좌측 패들 충돌
                if ball["x"] - ball["radius"] <= 22:
                    pad_y = paddle_positions["left"]
                    if pad_y - P_LEN / 2 <= ball["y"] <= pad_y + P_LEN / 2:
                        ball["vx"] = abs(ball["vx"])
                        step_vx = abs(step_vx)
                        offset = (ball["y"] - pad_y) / (P_LEN / 2)
                        ball["vy"] = offset * 5.5
                        step_vy = ball["vy"] / sub_steps
                    elif ball["x"] < -30:
                        reset_ball()
                        break

                # 우측 패들 충돌
                if ball["x"] + ball["radius"] >= WIDTH - 22:
                    pad_y = paddle_positions["right"]
                    if pad_y - P_LEN / 2 <= ball["y"] <= pad_y + P_LEN / 2:
                        ball["vx"] = -abs(ball["vx"])
                        step_vx = -abs(step_vx)
                        offset = (ball["y"] - pad_y) / (P_LEN / 2)
                        ball["vy"] = offset * 5.5
                        step_vy = ball["vy"] / sub_steps
                    elif ball["x"] > WIDTH + 30:
                        reset_ball()
                        break

                # 벽돌 AABB 정확한 충돌 검사
                r = ball["radius"]
                for b in bricks:
                    if b["alive"]:
                        if (ball["x"] + r >= b["x"] and ball["x"] - r <= b["x"] + b["w"] and
                            ball["y"] + r >= b["y"] and ball["y"] - r <= b["y"] + b["h"]):
                            b["alive"] = False
                            
                            # 충돌 면 분석 후 반사
                            prev_x = ball["x"] - step_vx
                            prev_y = ball["y"] - step_vy
                            if prev_x + r <= b["x"] or prev_x - r >= b["x"] + b["w"]:
                                ball["vx"] = -ball["vx"]
                                step_vx = -step_vx
                            else:
                                ball["vy"] = -ball["vy"]
                                step_vy = -step_vy
                            break

            # 스테이지 클리어 확인
            alive_count = sum(1 for b in bricks if b["alive"])
            if alive_count == 0:
                if current_stage < TOTAL_STAGES:
                    current_stage += 1
                    bricks = generate_stage(current_stage)
                    reset_ball()
                else:
                    # 모든 스테이지 완주 후 1스테이지 순환
                    current_stage = 1
                    bricks = generate_stage(current_stage)
                    reset_ball()

            # 인게임 상태 브로드캐스트
            bot_list = [role for role, occ in SLOTS.items() if occ == "BOT"]
            payload = json.dumps({
                "type": "game_update",
                "ball": ball,
                "paddles": paddle_positions,
                "bot_slots": bot_list,
                "stage": current_stage,
                "bricks": [b["id"] for b in bricks if not b["alive"]]
            })
            for ws in list(CONNECTED_CLIENTS.keys()):
                try:
                    await ws.send(payload)
                except:
                    pass

        await asyncio.sleep(0.016)

async def handler(websocket):
    CONNECTED_CLIENTS[websocket] = {"role": None}
    await broadcast_lobby()

    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "select_role":
                role = data.get("role")
                # 기존 슬롯 해제
                for r, occ in SLOTS.items():
                    if occ == websocket:
                        SLOTS[r] = "BOT"
                # 새 슬롯 점유
                if role in SLOTS and (SLOTS[role] == "BOT" or SLOTS[role] == websocket):
                    SLOTS[role] = websocket
                    CONNECTED_CLIENTS[websocket]["role"] = role
                await broadcast_lobby()

            elif msg_type == "start_game":
                global game_started, current_stage, bricks
                current_stage = 1
                bricks = generate_stage(current_stage)
                reset_ball()
                game_started = True
                init_payload = json.dumps({
                    "type": "game_start",
                    "stage": current_stage,
                    "bricks": bricks
                })
                for ws in list(CONNECTED_CLIENTS.keys()):
                    await ws.send(init_payload)

            elif msg_type == "move":
                role = CONNECTED_CLIENTS[websocket]["role"]
                if role and game_started:
                    paddle_positions[role] = data["pos"]

    except websockets.ConnectionClosed:
        pass
    finally:
        for r, occ in SLOTS.items():
            if occ == websocket:
                SLOTS[r] = "BOT"
        CONNECTED_CLIENTS.pop(websocket, None)
        await broadcast_lobby()

async def main():
    server = await websockets.serve(handler, "0.0.0.0", 8765)
    print(f"[{VERSION_TITLE}] 서버 가동 시작...")
    await asyncio.gather(server.wait_closed(), game_loop())

if __name__ == "__main__":
    asyncio.run(main())
