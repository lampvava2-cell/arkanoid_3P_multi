import asyncio
import json
import math
import random
import websockets

WIDTH = 500
HEIGHT = 500

VERSION_TITLE = "무수직반사_스코어버전8 (Angle Forced & Score System)"

SLOTS = {"bottom": None, "left": None, "right": None}
PLAYER_NAMES = {"bottom": "BOT", "left": "BOT", "right": "BOT"}
SCORES = {"bottom": 0, "left": 0, "right": 0}
CONNECTED_CLIENTS = {}

game_started = False
current_stage = 1
TOTAL_STAGES = 3
last_hitter = None  # 마지막으로 공을 친 슬롯 ("bottom", "left", "right")

paddle_positions = {
    "bottom": WIDTH / 2,
    "left": HEIGHT / 2,
    "right": HEIGHT / 2
}

BALL_BASE_SPEED = 6.8
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
    center_x, center_y = WIDTH / 2, HEIGHT / 2 - 20
    if stage_num == 1:
        rows, cols = 6, 6
        start_x = (WIDTH - (cols * 36)) / 2 + 3
        start_y = (HEIGHT - (rows * 22)) / 2 - 20
        for r in range(rows):
            for c in range(cols):
                new_bricks.append({"id": brick_id, "x": start_x + c * 36, "y": start_y + r * 22, "w": 30, "h": 14, "alive": True})
                brick_id += 1
    elif stage_num == 2:
        for r in range(7):
            for c in range(7):
                if r == 3 or c == 3 or (abs(r - 3) + abs(c - 3) <= 2):
                    new_bricks.append({"id": brick_id, "x": center_x - 126 + c * 36, "y": center_y - 77 + r * 22, "w": 30, "h": 14, "alive": True})
                    brick_id += 1
    else:
        for r in range(8):
            for c in range(8):
                if r in [0, 7] or c in [0, 7] or (r in [3, 4] and c in [3, 4]):
                    new_bricks.append({"id": brick_id, "x": center_x - 144 + c * 36, "y": center_y - 88 + r * 22, "w": 30, "h": 14, "alive": True})
                    brick_id += 1
    return new_bricks

def reset_ball():
    global ball, last_hitter
    ball["x"] = WIDTH / 2
    ball["y"] = HEIGHT / 2 + 80
    # 발사 시에도 완벽한 수직 발사 배제
    angle = random.choice([-1, 1]) * random.uniform(0.35, 0.75)
    ball["vx"] = BALL_BASE_SPEED * math.sin(angle)
    ball["vy"] = -abs(BALL_BASE_SPEED * math.cos(angle))
    last_hitter = None

bricks = generate_stage(current_stage)

def update_ai():
    ai_speed = 6.2
    if SLOTS["bottom"] is None:
        tx = ball["x"]
        cx = paddle_positions["bottom"]
        paddle_positions["bottom"] += max(-ai_speed, min(ai_speed, tx - cx))
        paddle_positions["bottom"] = max(40, min(WIDTH - 40, paddle_positions["bottom"]))

    if SLOTS["left"] is None:
        ty = ball["y"]
        cy = paddle_positions["left"]
        paddle_positions["left"] += max(-ai_speed, min(ai_speed, ty - cy))
        paddle_positions["left"] = max(40, min(HEIGHT - 40, paddle_positions["left"]))

    if SLOTS["right"] is None:
        ty = ball["y"]
        cy = paddle_positions["right"]
        paddle_positions["right"] += max(-ai_speed, min(ai_speed, ty - cy))
        paddle_positions["right"] = max(40, min(HEIGHT - 40, paddle_positions["right"]))

async def broadcast_lobby():
    slots_info = {}
    for role in ["bottom", "left", "right"]:
        ws = SLOTS[role]
        slots_info[role] = {"type": "BOT" if ws is None else "USER", "name": PLAYER_NAMES[role]}

    waiting_users = [info["name"] for ws, info in CONNECTED_CLIENTS.items() if info["state"] == "waiting"]

    payload = json.dumps({
        "type": "lobby_state",
        "title": VERSION_TITLE,
        "slots": slots_info,
        "scores": SCORES,
        "game_started": game_started,
        "waiting_users": waiting_users,
        "stage": current_stage
    })
    for ws in list(CONNECTED_CLIENTS.keys()):
        try:
            await ws.send(payload)
        except:
            pass

def enforce_non_vertical(vx, vy, base_dir="y"):
    """수직/수평 단조 궤적 완전 제거 및 속도 정규화"""
    min_component = 2.4
    if base_dir == "y":
        # 하단 패들 반사: 수직(vx=0) 방지
        if abs(vx) < min_component:
            vx = min_component if vx >= 0 else -min_component
    else:
        # 좌/우 패들 반사: 수평(vy=0) 방지
        if abs(vy) < min_component:
            vy = min_component if vy >= 0 else -min_component

    current_speed = math.hypot(vx, vy)
    scale = BALL_BASE_SPEED / current_speed
    return vx * scale, vy * scale

async def game_loop():
    global game_started, current_stage, bricks, ball, last_hitter
    P_LEN = 70

    while True:
        if game_started:
            update_ai()

            sub_steps = 4
            step_vx = ball["vx"] / sub_steps
            step_vy = ball["vy"] / sub_steps

            for _ in range(sub_steps):
                ball["x"] += step_vx
                ball["y"] += step_vy

                # 1. 상단 천장 반사
                if ball["y"] - ball["radius"] <= 10:
                    ball["y"] = 10 + ball["radius"]
                    ball["vy"] = abs(ball["vy"])
                    ball["vx"], ball["vy"] = enforce_non_vertical(ball["vx"], ball["vy"], "y")
                    step_vx = ball["vx"] / sub_steps
                    step_vy = ball["vy"] / sub_steps

                # 2. 하단 패들 충돌
                if ball["y"] + ball["radius"] >= HEIGHT - 22:
                    pad_x = paddle_positions["bottom"]
                    if pad_x - P_LEN / 2 <= ball["x"] <= pad_x + P_LEN / 2:
                        ball["y"] = HEIGHT - 22 - ball["radius"]
                        offset = (ball["x"] - pad_x) / (P_LEN / 2)
                        
                        # [무수직 반사] 정중앙 타격 시 강제로 최소 20도 각도 부여
                        if abs(offset) < 0.22:
                            offset = 0.35 if offset >= 0 else -0.35
                        
                        rebound_angle = offset * (math.pi / 2.8)
                        ball["vx"] = BALL_BASE_SPEED * math.sin(rebound_angle)
                        ball["vy"] = -BALL_BASE_SPEED * math.cos(rebound_angle)
                        ball["vx"], ball["vy"] = enforce_non_vertical(ball["vx"], ball["vy"], "y")
                        step_vx = ball["vx"] / sub_steps
                        step_vy = ball["vy"] / sub_steps
                        last_hitter = "bottom"
                    elif ball["y"] > HEIGHT + 30:
                        SCORES["bottom"] = max(0, SCORES["bottom"] - 200)  # 실점
                        reset_ball()
                        break

                # 3. 좌측 패들 충돌
                if ball["x"] - ball["radius"] <= 22:
                    pad_y = paddle_positions["left"]
                    if pad_y - P_LEN / 2 <= ball["y"] <= pad_y + P_LEN / 2:
                        ball["x"] = 22 + ball["radius"]
                        offset = (ball["y"] - pad_y) / (P_LEN / 2)
                        if abs(offset) < 0.22:
                            offset = -0.35  # 상향 각도 편향
                        
                        adj_offset = max(-1.0, min(1.0, offset - 0.2))
                        rebound_angle = adj_offset * (math.pi / 2.9)
                        ball["vx"] = BALL_BASE_SPEED * math.cos(rebound_angle)
                        ball["vy"] = BALL_BASE_SPEED * math.sin(rebound_angle)
                        ball["vx"], ball["vy"] = enforce_non_vertical(ball["vx"], ball["vy"], "x")
                        step_vx = ball["vx"] / sub_steps
                        step_vy = ball["vy"] / sub_steps
                        last_hitter = "left"
                    elif ball["x"] < -30:
                        SCORES["left"] = max(0, SCORES["left"] - 200)  # 실점
                        reset_ball()
                        break

                # 4. 우측 패들 충돌
                if ball["x"] + ball["radius"] >= WIDTH - 22:
                    pad_y = paddle_positions["right"]
                    if pad_y - P_LEN / 2 <= ball["y"] <= pad_y + P_LEN / 2:
                        ball["x"] = WIDTH - 22 - ball["radius"]
                        offset = (ball["y"] - pad_y) / (P_LEN / 2)
                        if abs(offset) < 0.22:
                            offset = -0.35
                        
                        adj_offset = max(-1.0, min(1.0, offset - 0.2))
                        rebound_angle = adj_offset * (math.pi / 2.9)
                        ball["vx"] = -BALL_BASE_SPEED * math.cos(rebound_angle)
                        ball["vy"] = BALL_BASE_SPEED * math.sin(rebound_angle)
                        ball["vx"], ball["vy"] = enforce_non_vertical(ball["vx"], ball["vy"], "x")
                        step_vx = ball["vx"] / sub_steps
                        step_vy = ball["vy"] / sub_steps
                        last_hitter = "right"
                    elif ball["x"] > WIDTH + 30:
                        SCORES["right"] = max(0, SCORES["right"] - 200)  # 실점
                        reset_ball()
                        break

                # 5. 벽돌 정밀 충돌 판정 및 점수 계산
                r = ball["radius"]
                for b in bricks:
                    if not b["alive"]:
                        continue

                    closest_x = max(b["x"], min(ball["x"], b["x"] + b["w"]))
                    closest_y = max(b["y"], min(ball["y"], b["y"] + b["h"]))

                    dist_x = ball["x"] - closest_x
                    dist_y = ball["y"] - closest_y

                    if (dist_x * dist_x + dist_y * dist_y) < (r * r):
                        b["alive"] = False
                        
                        # [득점 시스템] 마지막 타격자에게 100점 가산
                        if last_hitter in SCORES:
                            SCORES[last_hitter] += 100

                        overlap_left = (ball["x"] + r) - b["x"]
                        overlap_right = (b["x"] + b["w"]) - (ball["x"] - r)
                        overlap_top = (ball["y"] + r) - b["y"]
                        overlap_bottom = (b["y"] + b["h"]) - (ball["y"] - r)

                        if min(overlap_left, overlap_right) < min(overlap_top, overlap_bottom):
                            ball["vx"] = -ball["vx"]
                            step_vx = -step_vx
