"""
[Experiment] Step 1-5 LangGraph 실행 스크립트
- test_steps_1_5.py의 답변 데이터를 미리 State에 주입
- 별도의 입력 절차 없이 Step 1 ~ 5가 연속으로 실행됨 (Human Review에서만 멈춤)
- Step 5 완료 후 자동 종료
"""
import os
import json
import time  # timestamp 추가
from dotenv import load_dotenv
from langgraph_system.graph import create_info_graph
from langgraph_system.state import create_initial_state
from database.connection import db_connection

# 환경 변수 로드
load_dotenv()

def main():
    print("🧪 [Experiment] Step 1-5 실험을 시작합니다...")
    print("   - 사전 정의된 답변 데이터를 사용합니다.")
    print("   - Step 5 완료 시 자동 종료됩니다.")
    
    # 1. DB 연결 (옵션)
    if os.getenv("ENABLE_DB", "false").lower() == "true":
        if db_connection.connect():
            print("[System] ✅ DB 연결 성공")
        else:
            print("[System] ❌ DB 연결 실패 (로컬 모드)")
    else:
        print("[System] DB 미사용 모드 (Local Mode)")

    # 2. 초기화 (Timestamp를 이용해 매번 새로운 세션 생성)
    timestamp = int(time.time())
    brand_id = f"test_brand_1to5_{timestamp}"
    user_id = "experimenter"
    
    print(f"[System] Brand ID: {brand_id} (새로운 세션)")
    
    app = create_info_graph()
    initial_state = create_initial_state(brand_id, user_id)
    
    # 3. 데이터 주입 (answers.json 사용)
    print("\n[System] answers.json 데이터 로드 중...", end="")
    
    try:
        with open("answers.json", "r", encoding="utf-8") as f:
            answers_data = json.load(f)["answers"]
            
        initial_state["step_1_qa"] = answers_data.get("step_1", {})
        initial_state["step_2_qa"] = answers_data.get("step_2", {})
        initial_state["step_3_qa"] = answers_data.get("step_3", {})
        initial_state["step_4_qa"] = answers_data.get("step_4", {})
        initial_state["step_5_qa"] = answers_data.get("step_5", {})
        
        # Step 1부터 시작하도록 명시
        initial_state["current_step"] = 1

        print(" 완료 (Step 1~5 QA 데이터)\n")
        
    except FileNotFoundError:
        print("\n❌ answers.json 파일을 찾을 수 없습니다.")
        return
    except json.JSONDecodeError:
        print("\n❌ answers.json 파싱 오류.")
        return
    
    # 4. 실행 루프
    thread_config = {"configurable": {"thread_id": f"thread_{brand_id}"}}
    print(f"[Start] 1-5단계 실험 시작...")
    
    current_input = initial_state
    
    while True:
        try:
            for event in app.stream(current_input, thread_config):
                for key, value in event.items():
                    if key != "__end__":
                        print(f"\n📍 Node Completed: {key}")
        except Exception as e:
            print(f"\n❌ 실행 중 오류 발생: {e}")
            break

        # 실행 상태 확인
        snapshot = app.get_state(thread_config)
        
        # 종료 조건 1: 실행할 노드가 없음
        if not snapshot.next:
            print("\n[System] 워크플로우 종료")
            break
            
        current_state = snapshot.values
        
        # [에러 체크] 노드 실행 중 에러 발생 시 중단
        if current_state.get("error_occurred"):
            print(f"\n❌ 노드 실행 중 에러가 발생하여 중단합니다.")
            print(f"   Error Message: {current_state.get('error_message')}")
            break
            
        step = current_state.get("current_step")
        next_node = snapshot.next[0]
        
        # 종료 조건 2: Logo Human Review 완료 (experiment_completed 플래그)
        if current_state.get("experiment_completed"):
            print(f"\n✅ [Experiment] Step 5까지 완료되었습니다. 실험을 종료합니다.")
            
            # 결과 저장 수행
            save_experiment_results(current_state)
            break
        
        # Human Review 처리 - 3개 후보 선택
        if next_node == "human_review":
            # Step 매핑 (candidates가 있는 단계만 정의)
            step_mappings = {
                3: ("naming_candidates", "Naming"),
                4: ("concept_candidates", "Concept"),
                5: ("story_candidates", "Story"),
                6: ("logo_candidates", "Logo")
            }
            
            # Step 1 (Diagnosis) 등 후보 선택이 없는 단계는 자동 통과
            if step not in step_mappings:
                if step == 2:
                    print(f"\n{'='*50}")
                    print(f"✅ [Step 1: Diagnosis] 완료 (자동 승인)")
                    print(f"{'='*50}\n")
                else:
                    print(f"\n{'='*50}")
                    print(f"✋ [Human Review] Step {step - 1} - 자동 승인 (후보 없음)")
                    print(f"{'='*50}\n")
                
                app.update_state(thread_config, {"user_choice": "0"}, as_node="human_review")
                current_input = None
                continue
            
            candidates_key, step_name = step_mappings[step]
            candidates = current_state.get(candidates_key, [])
            
            if not candidates:
                print(f"\n⚠️ Step {step-1} ({step_name}) 후보 데이터가 없습니다.")
                print(f"   이전 노드가 정상적으로 실행되지 않았을 수 있습니다.")
                print(f"   실험을 중단합니다.")
                break
            
            # ------------------------------------------------------------------
            # [Logo Step (Step 6) Special Handling]
            # ------------------------------------------------------------------
            if step == 6:
                print(f"\n{'='*60}")
                print(f"🎨 [Logo Selection] 생성된 3개 로고 이미지 중 하나를 선택하세요")
                print(f"{'='*60}\n")
                
                for i, cand in enumerate(candidates):
                    output = cand.get("output", {})
                    img_url = output.get("logo_image_url")
                    print(f"[Option {i}]")
                    # logo_concept은 50자까지만 표시
                    print(f"  Concept: {output.get('logo_concept', 'N/A')[:50]}...")
                    if img_url:
                        print(f"  URL: {img_url}")
                        # 파일 경로는 참고용
                        print(f"  Path: {output.get('logo_image_path', 'N/A')}")
                    else:
                        print(f"  ❌ 이미지 생성 실패")
                    print("-" * 30)

                img_choice = input("\n최종 로고 선택 (0, 1, 2) 또는 r(재생성): ").strip().lower()
                
                if img_choice == 'r':
                    feedback = input("재생성 피드백 (한국어): ")
                    if not feedback: feedback = "다시 생성해주세요"
                    
                    app.update_state(
                        thread_config,
                        {
                            "user_choice": "regenerate",
                            "feedback_content": feedback,
                            "regenerate_step": step - 1,
                            "current_step": step - 1, # step 6 (Logo) 상태 유지하며 로직 재실행
                            "quality_check_passed": False,
                            "feedback_required": True
                        },
                        as_node="human_review"
                    )
                    current_input = None
                    continue

                elif img_choice in ['0', '1', '2']:
                    selected_idx = int(img_choice)
                    if selected_idx < len(candidates):
                        selected_candidate = candidates[selected_idx]
                        
                        # 최종 결과 구성 (불필요한 필드 제거는 save_experiment에서 처리)
                        final_result = {
                           "analysis": selected_candidate.get("analysis", {}),
                           "output": selected_candidate.get("output", {})
                        }
                        
                        # Update Data
                        update_data = {
                            "logo_result": final_result,
                            "logo_context": {
                                "logo_rationale": final_result["output"].get("logo_concept", ""), # Rationale 대체
                                "logo_image_url": final_result["output"].get("logo_image_url")
                            },
                            "experiment_completed": True,
                            "user_choice": str(selected_idx),
                            "quality_check_passed": True
                        }
                        
                        # State 업데이트
                        app.update_state(thread_config, update_data, as_node="human_review")
                        print(f"[System] ✅ 로고 선택 및 저장 완료!")
                        print(f"\n✅ [Experiment] Step 5까지 완료되었습니다. 실험을 종료합니다.")
                        
                        # 여기서 즉시 break 하기 위해 저장 호출
                        save_experiment_results(app.get_state(thread_config).values)
                        break
                    else:
                        print("⚠️ 잘못된 선택입니다.")
                        break
                else:
                     print("⚠️ 잘못된 입력입니다.")
                     break
                
            # ------------------------------------------------------------------
            # [Normal Steps (Naming, Concept, Story)]
            # ------------------------------------------------------------------
            else:
                print(f"\n{'='*60}")
                print(f"✋ [Human Review] Step {step - 1}: {step_name}")
                print(f"{'='*60}")
                print(f"\n3개 후보 중 선택해주세요:\n")
                
                for i, cand in enumerate(candidates):
                    output = cand.get("output", {})
                    print(f"\n{'─'*50}")
                    print(f"[후보 {i}]")
                    
                    if step == 3:  # Naming
                        print(f"  브랜드명: {output.get('brand_name', 'N/A')}")
                        print(f"  선정 이유: {output.get('name_rationale', 'N/A')[:100]}...")
                    
                    elif step == 4:  # Concept
                        print(f"  컨셉 선언문: {output.get('concept_statement', 'N/A')[:100]}...")
                        print(f"  컨셉 이유: {output.get('concept_rationale', 'N/A')[:100]}...")
                    
                    elif step == 5:  # Story
                        print(f"  브랜드 스토리: {output.get('brand_story', 'N/A')[:150]}...")
                
                print(f"\n{'─'*50}")
                print(f"\n선택하세요:")
                print(f"  0, 1, 2  : 후보 선택")
                print(f"  r        : 재생성 (피드백 입력)")
                
                choice = input("\n>> ").strip().lower()
                
                if choice == 'r':
                    feedback = input("재생성 피드백 (한국어): ")
                    if not feedback:
                        feedback = "다시 생성해주세요"
                    print(f"[User] 재생성 요청: {feedback}")
                    
                    target_step = step - 1
                    
                    app.update_state(
                        thread_config,
                        {
                            "user_choice": "regenerate",
                            "feedback_content": feedback,
                            "regenerate_step": target_step,
                            "current_step": target_step,
                            "quality_check_passed": False,
                            "feedback_required": True
                        },
                        as_node="human_review"
                    )
                elif choice in ['0', '1', '2']:
                    print(f"[User] 후보 {choice} 선택")
                    selected_idx = int(choice)
                    if selected_idx < len(candidates):
                        selected_candidate = candidates[selected_idx]
                        
                        final_result = {
                            "analysis": selected_candidate.get("analysis", {}),
                            "output": selected_candidate.get("output", {})
                        }
                        
                        output_data = final_result["output"]
                        core_context = {}
                        context_key = None
                        
                        if step == 3:
                            context_key = "naming_context"
                            core_context = {
                                "brand_name": output_data.get("brand_name"),
                                "name_rationale": output_data.get("name_rationale")
                            }
                        elif step == 4:
                            context_key = "concept_context"
                            core_context = {
                                "concept_statement": output_data.get("concept_statement"),
                                "concept_rationale": output_data.get("concept_rationale")
                            }
                        elif step == 5:
                            context_key = "story_context"
                            core_context = {
                                "brand_story": output_data.get("brand_story"),
                                "story_rationale": output_data.get("story_rationale")
                            }

                        update_data = {
                            "user_choice": choice,
                            "quality_check_passed": True,
                            "feedback_required": False,
                            "regenerate_step": None
                        }
                        
                        result_keys = {3: "naming_result", 4: "concept_result", 5: "story_result"}
                        result_key = result_keys.get(step)
                        
                        if result_key:
                            update_data[result_key] = final_result
                        
                        if context_key and core_context:
                            update_data[context_key] = core_context
                            print(f"[System] Core Context 추출: {context_key}")

                        app.update_state(thread_config, update_data, as_node="human_review")
                        print(f"[System] 후보 선택 결과 및 Context 저장 완료")
                        print(f"\n[System] 선택 완료, 워크플로우 계속...\n")
                
                current_input = None
        else:
            # 다른 중단점이면 계속 진행
             current_input = None

def filter_backend_data(step_num, output_data):
    """
    백엔드 전송용 데이터 필터링
    각 Step별로 핵심 결과물만 추출
    """
    if step_num == 1:  # Diagnosis - 전체 분석 내용
        return output_data  # 전체 Q&A 분석 내용
    
    elif step_num == 2:  # Naming - 브랜드명만
        return {
            "brand_name": output_data.get("brand_name", "")
        }
    
    elif step_num == 3:  # Concept - 컨셉 선언문만
        return {
            "concept_statement": output_data.get("concept_statement", "")
        }
    
    elif step_num == 4:  # Story - 브랜드 스토리만
        return {
            "brand_story": output_data.get("brand_story", "")
        }
    
    elif step_num == 5:  # Logo - 이미지 URL만
        return {
            "logo_image_url": output_data.get("logo_image_url", None)
        }
    
    else:
        # 기본값: 전체 반환
        return output_data

def save_experiment_results(state):
    """
    실험 결과를 단계별 폴더에 저장 + 브랜드 컨설팅 리포트 생성
    """
    import shutil
    from langgraph_system.utils import get_openai_client
    
    brand_id = state.get("brand_id", "test_brand")
    base_dir = f"outputs/{brand_id}"
    os.makedirs(base_dir, exist_ok=True)
    
    print(f"\n[System] 결과물을 '{base_dir}' 폴더에 저장합니다...")
    
    # DB 연결 확인
    try:
        from database.connection import db_connection
        from database.operations import save_brand_result, update_brand_step
        db_available = db_connection is not None
    except Exception as e:
        print(f"\n⚠️ DB 연결 실패: {e}")
        db_available = False
    
    # 3. 단계별 결과 저장 (후보 3개 + 선택된 결과) + 백엔드 전송
    rag_context = {}
    
    steps_info = {
        1: ("diagnosis", "diagnosis_result", None),  # Step 1은 후보 없음
        2: ("naming", "naming_result", "naming_candidates"),
        3: ("concept", "concept_result", "concept_candidates"),
        4: ("story", "story_result", "story_candidates"),
        5: ("logo", "logo_result", "logo_candidates")
    }
    
    for step_num, (name, result_key, candidates_key) in steps_info.items():
        step_dir = os.path.join(base_dir, f"step_{step_num}_{name}")
        os.makedirs(step_dir, exist_ok=True)
        
        # 선택된 결과
        result_data = state.get(result_key)
        
        # 후보들
        candidates = state.get(candidates_key, []) if candidates_key else []
        
        # 선택 인덱스
        selected_index_key = f"{name}_selected_index"
        selected_index = state.get(selected_index_key)
        
        # 1. Output/Analysis 데이터 준비
        analysis_data = state.get(f"step_{step_num}_analysis", {})
        if not analysis_data and result_data and "analysis" in result_data:
            analysis_data = result_data["analysis"]
        
        output_data = {}
        if result_data:
            if "output" in result_data:
                output_data = result_data.get("output", {})
            elif step_num == 1 and "analysis" in result_data:
                output_data = result_data["analysis"]

        # 2. [JSON 구조 최적화] 사용자 요청에 따른 필드 필터링
        final_output_data = output_data.copy()
        
        if step_num == 2: # Naming
            final_output_data = {
                "brand_name": output_data.get("brand_name"),
                "name_rationale": output_data.get("name_rationale")
            }
        elif step_num == 3: # Concept
            final_output_data = {
                "concept_statement": output_data.get("concept_statement"),
                "concept_rationale": output_data.get("concept_rationale")
            }
        elif step_num == 5: # Logo
             final_output_data = {
                "logo_concept": output_data.get("logo_concept"),
                "logo_image_url": output_data.get("logo_image_url")
            }
             # 이미지 파일 복사
             img_path = output_data.get("logo_image_path")
             if img_path and os.path.exists(img_path):
                 try:
                     shutil.copy2(img_path, os.path.join(step_dir, os.path.basename(img_path)))
                 except: pass

        # 3. 백엔드 전송 (핵심 결과물만 전송)
        if db_available and final_output_data:
            try:
                # Step별 핵심 데이터만 필터링
                backend_data = filter_backend_data(step_num, final_output_data)  # 필터링된 데이터 사용
                
                session = db_connection.get_session()
                save_brand_result(
                    session=session,
                    brand_id=state["brand_id"],
                    step_name=name,
                    result_data=backend_data
                )
                update_brand_step(session, state["brand_id"], step_num + 1)
                session.close()
                print(f"  [Step {step_num}] ✅ 백엔드 전송 완료")
            except Exception as e:
                print(f"  [Step {step_num}] ⚠️ 백엔드 전송 실패: {e}")
        
        # 4. result.json 저장
        final_result_json = {}
        
        if step_num == 1:
            # Step 1: Output(Analysis) + QA (No separate qa.json)
            qa_data = result_data.get("qa", {}) if result_data else {}
            final_result_json = {
                "output": final_output_data, # Analysis
                "qa": qa_data
            }
        
        else:
            # Step 2-5
            
            # [Logo Step] JSON 저장용 Candidates 전처리 (logo_image_path 제거)
            json_candidates = candidates
            if step_num == 5:
                json_candidates = []
                for cand in candidates:
                    # 원본 State 보호를 위해 Deep Copy에 준하는 처리
                    new_cand = cand.copy()
                    if "output" in new_cand:
                        new_output = new_cand["output"].copy()
                        new_output.pop("logo_image_path", None)
                        new_cand["output"] = new_output
                    json_candidates.append(new_cand)

            # [수정] analysis 제거 및 selected_result 평탄화 (user request)
            final_result_json = {
                "candidates": json_candidates,  # Cleaned candidates
                "selected_index": selected_index,
                "selected_result": final_output_data # analysis 제거, outputWrapper 제거 -> 바로 핵심 데이터 (brand_name, rationale 등)
            }
            # Step 2~5는 qa.json 별도 생성 (기존 유지)
            if result_data and "qa" in result_data:
                with open(os.path.join(step_dir, "qa.json"), "w", encoding="utf-8") as f:
                    json.dump(result_data["qa"], f, ensure_ascii=False, indent=2)

        with open(os.path.join(step_dir, "result.json"), "w", encoding="utf-8") as f:
            json.dump(final_result_json, f, ensure_ascii=False, indent=2)

        # 5. RAG Context 데이터 축적 (최적화된 Output만)
        # [수정] analysis 제거 (user request)
        rag_context[f"step_{step_num}"] = final_output_data

    # 4. RAG Context 저장
    rag_file = os.path.join(base_dir, "rag_context.json")
    with open(rag_file, "w", encoding="utf-8") as f:
        json.dump(rag_context, f, ensure_ascii=False, indent=2)
    print(f"  - RAG Context 저장 완료: {rag_file}")
    
    # 5. 브랜드 컨설팅 리포트 생성 (Step 1-5 종합)
    print(f"\n[System] 브랜드 컨설팅 리포트 생성 중...")
    try:
        client = get_openai_client()
        
        # Step 1-5 데이터를 종합하여 리포트 생성을 위한 컨텍스트 구성
        report_context = {
            "brand_name": state.get("naming_result", {}).get("output", {}).get("brand_name", ""),
            "diagnosis": state.get("diagnosis_result", {}).get("analysis", {}),
            "naming": state.get("naming_result", {}).get("output", {}),
            "concept": state.get("concept_result", {}).get("output", {}),
            "story": state.get("story_result", {}).get("output", {}),
            "logo": state.get("logo_result", {}).get("output", {})
        }
        
        system_prompt = (
            "You are a Senior Brand Consulting Advisor. "
            "Analyze the brand consulting results (Steps 1-5) and generate a comprehensive consulting report in Korean. "
            "The report should include: overall analysis, strengths, weaknesses, future direction, and recommendations."
        )
        
        user_prompt = f"""
[Brand Consulting Results - Steps 1-5]
{json.dumps(report_context, ensure_ascii=False, indent=2)}

[Task]
Based on the above brand consulting results, create a comprehensive brand consulting report in Korean.

The report must include:
1. overall_analysis: 브랜드 전체에 대한 종합 분석 (2-3문장, 한국어)
2. strengths: 브랜드의 강점 5가지 (배열, 각 항목 한국어)
3. weaknesses: 브랜드의 약점/개선점 5가지 (배열, 각 항목 한국어)
4. future_direction: 향후 발전 방향 제안 (2-3문장, 한국어)
5. recommendations: 구체적인 추천 사항 5가지 (배열, 각 항목 한국어)

Output JSON format:
{{
  "overall_analysis": "브랜드 종합 분석...",
  "strengths": ["강점1", "강점2", "강점3", "강점4", "강점5"],
  "weaknesses": ["약점1", "약점2", "약점3", "약점4", "약점5"],
  "future_direction": "향후 발전 방향...",
  "recommendations": ["추천1", "추천2", "추천3", "추천4", "추천5"]
}}

IMPORTANT: All content must be in Korean.
"""
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"}
        )
        
        brand_report = json.loads(response.choices[0].message.content)
        
        # 브랜드 컨설팅 리포트 저장
        report_file = os.path.join(base_dir, "brand_consulting_report.json")
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(brand_report, f, ensure_ascii=False, indent=2)
        
        print(f"  - 브랜드 컨설팅 리포트 저장 완료: {report_file}")
        
    except Exception as e:
        print(f"  - ⚠️ 브랜드 컨설팅 리포트 생성 실패: {e}")
    
    print("\n✅ 모든 결과 저장 완료! (모든 상세 정보 포함)")

if __name__ == "__main__":
    main()
