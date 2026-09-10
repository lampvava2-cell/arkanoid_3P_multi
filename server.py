import asyncio
import json
import math
import random
import websockets

# 가상 해상도 기준 좌표계
WIDTH = 400
HEIGHT = 600

# 3방향 플레이어 슬롯 및 역할
PLAYERS = {}  # websocket: role
ROLES = ["bottom", "left", "right"]
AVAILABLE_ROLES = list(ROLES)

# 패들 기본 위치
paddle_positions = {
    "bottom": WIDTH / 2,
    "left": HEIGHT / 2,
    "right": HEIGHT / 2
}

# 공 기본 상태
ball = {
    "x": WIDTH / 2,
    "y": HEIGHT / 2 + 100,
    "vx": 5.5,
    "vy": -5.5,
    "radius": 8
}

# 중앙 5x5 벽돌 배치
bricks = []
BRICK_ROWS = 5
BRICK_COLS = 5
BRICK_WIDTH = 30
BRICK_HEIGHT = 15

def init_bricks():
    global bricks
    bricks = []
    start_x = (WIDTH - (BRICK_COLS * 35)) / 2 + 2.5
    start_y = (HEIGHT - (BRICK_ROWS * 22)) / 2 - 20
    for r in range(BRICK_ROWS):
        for c in range(BRICK_COLS):
            bricks.append({
                "id": r * BRICK_COLS + c,
                "x": start_x + c * 35,
                "y": start_y + r * 22,
                "w": BRICK_WIDTH,
                "h": BRICK_HEIGHT,
                "alive": True
            })

init_bricks()

async def register(ws):
    if len(AVAILABLE_ROLES) > 0:
        role = AVAILABLE_ROLES.pop(0)
        PLAYERS[ws] = role
        await ws.send(json.dumps({
            "type": "init", 
            "role": role, 
            "bricks": bricks,
            "active_players": list(PLAYERS.values())
        }))
        print(f"[접속] 인간 플레이어 배정: {role} (봇 운영 슬롯: {AVAILABLE_ROLES})")
    else:
        await ws.send(json.dumps({"type": "full"}))

async def unregister(ws):
    if ws in PLAYERS:
        role = PLAYERS.pop(ws)
        AVAILABLE_ROLES.insert(0, role)
        print(f"[퇴장] {role} 이탈 -> 봇이 제어권 인수 (봇 운영 슬롯: {AVAILABLE_ROLES})")

def update_ai_bots():
    """사람이 없는 빈자리는 컴퓨터 AI가 공의 위치를 추적하여 패들을 조작"""
    ai_speed = 6.0

    # 1. 하단 슬롯이 비었을 때 (X축 추적)
    if "bottom" in AVAILABLE_ROLES:
        target_x = ball["x"]
        curr_x = paddle_positions["bottom"]
        if curr_x < target_x - 5:
            paddle_positions["bottom"] = min(WIDTH - 35, curr_x + ai_speed)
        elif curr_x > target_x + 5:
            paddle_positions["bottom"] = max(35, curr_x - ai_speed)

    # 2. 좌측 슬롯이 비었을 때 (Y축 추적)
    if "left" in AVAILABLE_ROLES:
        target_y = ball["y"]
        curr_y = paddle_positions["left"]
        if curr_y < target_y - 5:
            paddle_positions["left"] = min(HEIGHT - 35, curr_y + ai_speed)
        elif curr_y > target_y + 5:
            paddle_positions["left"] = max(35, curr_y - ai_speed)

    # 3. 우측 슬롯이 비었을 때 (Y축 추적)
    if "right" in AVAILABLE_ROLES:
        target_y = ball["y"]
        curr_y = paddle_positions["right"]
        if curr_y < target_y - 5:
            paddle_positions["right"] = min(HEIGHT - 35, curr_y + ai_speed)
        elif curr_y > target_y + 5:
            paddle_positions["right"] = max(35, curr_y - ai_speed)

async def game_loop():
    global ball
    PADDLE_LENGTH = 65

    while True:
        # 빈 슬롯 AI 봇 이동 계산
        update_ai_bots()

        # 공 이동
        ball["x"] += ball["vx"]
        ball["y"] += ball["vy"]

        # 1. 상단 벽 충돌 (상단은 벽으로 방어)
        if ball["y"] - ball["radius"] <= 10:
            ball["y"] = 10 + ball["radius"]
            ball["vy"] = abs(ball["vy"])

        # 2. 하단 패들 충돌 판정
        if ball["y"] + ball["radius"] >= HEIGHT - 22:
            pad_x = paddle_positions["bottom"]
            if pad_x - PADDLE_LENGTH / 2 <= ball["x"] <= pad_x + PADDLE_LENGTH / 2:
                ball["vy"] = -abs(ball["vy"])
                offset = (ball["x"] - pad_x) / (PADDLE_LENGTH / 2)
                ball["vx"] = offset * 6.0
            elif ball["y"] > HEIGHT + 25:
                ball["x"], ball["y"] = WIDTH / 2, HEIGHT / 2 + 80
                ball["vx"], ball["vy"] = random.choice([-3.0, 3.0]), -3.2

        # 3. 좌측 패들 충돌 판정
        if ball["x"] - ball["radius"] <= 22:
            pad_y = paddle_positions["left"]
            if pad_y - PADDLE_LENGTH / 2 <= ball["y"] <= pad_y + PADDLE_LENGTH / 2:
                ball["vx"] = abs(ball["vx"])
                offset = (ball["y"] - pad_y) / (PADDLE_LENGTH / 2)
                ball["vy"] = offset * 6.0
            elif ball["x"] < -25:
                ball["x"], ball["y"] = WIDTH / 2, HEIGHT / 2
                ball["vx"], ball["vy"] = 3.2, random.choice([-3.0, 3.0])

        # 4. 우측 패들 충돌 판정
        if ball["x"] + ball["radius"] >= WIDTH - 22:
            pad_y = paddle_positions["right"]
            if pad_y - PADDLE_LENGTH / 2 <= ball["y"] <= pad_y + PADDLE_LENGTH / 2:
                ball["vx"] = -abs(ball["vx"])
                offset = (ball["y"] - pad_y) / (PADDLE_LENGTH / 2)
                ball["vy"] = offset * 4.2
            elif ball["x"] > WIDTH + 25:
                ball["x"], ball["y"] = WIDTH / 2, HEIGHT / 2
                ball["vx"], ball["vy"] = -3.2, random.choice([-3.0, 3.0])

        # 5. 벽돌 충돌 및 파괴
        for b in bricks:
            if b["alive"]:
                if (b["x"] <= ball["x"] <= b["x"] + b["w"] and
                    b["y"] <= ball["y"] <= b["y"] + b["h"]):
                    b["alive"] = False
                    ball["vy"] = -ball["vy"]
                    break

        # 6. 전체 플레이어 동기화 패킷 전송
        if PLAYERS:
            payload = json.dumps({
                "type": "update",
                "ball": ball,
                "paddles": paddle_positions,
                "bot_slots": AVAILABLE_ROLES,
                "bricks": [b["id"] for b in bricks if not b["alive"]]
            })
            await asyncio.gather(*[ws.send(payload) for ws in PLAYERS.keys()], return_exceptions=True)

        await asyncio.sleep(0.012)

async def handler(websocket):
    await register(websocket)
    try:
        async for message in websocket:
            data = json.loads(message)
            if data["type"] == "move":
                role = PLAYERS.get(websocket)
                if role:
                    paddle_positions[role] = data["pos"]
    except websockets.ConnectionClosed:
        pass
    finally:
        await unregister(websocket)

async def main():
    server = await websockets.serve(handler, "0.0.0.0", 8765)
    print("3인 알카노이드(AI 봇 내장) 서버 실행 중... 포트: 8765")
    await asyncio.gather(server.wait_closed(), game_loop())

if __name__ == "__main__":
    asyncio.run(main())
