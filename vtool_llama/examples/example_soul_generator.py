import sys
import os
import time
import json
import msvcrt

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from vtool_llama import VToolLlama, Genome, PsychologyState, PersonaState

def timed_input(prompt, timeout=60, default="Tu elige"):
    print(prompt, end="", flush=True)
    start_time = time.time()
    input_chars = []
    
    while True:
        if time.time() - start_time >= timeout:
            print(f"\n[Tiempo agotado! Usando valor por defecto: '{default}']")
            return default
        
        if msvcrt.kbhit():
            try:
                char_b = msvcrt.getch()
                char = char_b.decode('utf-8', errors='ignore')
            except Exception:
                char = ''
            
            if char == '\r' or char == '\n':
                print()
                break
            elif char == '\x08':  # Backspace
                if input_chars:
                    input_chars.pop()
                    sys.stdout.write('\b \b')
                    sys.stdout.flush()
            elif char == '\x03':  # Ctrl+C
                raise KeyboardInterrupt()
            elif char:
                input_chars.append(char)
                sys.stdout.write(char)
                sys.stdout.flush()
        else:
            time.sleep(0.05)
            
    return "".join(input_chars)

def get_input(prompt, default="Tu elige", timeout=60, auto_enabled=False):
    if auto_enabled:
        return timed_input(prompt, timeout=timeout, default=default)
    return input(prompt)

def update_character_state_with_soul(char_name, llm):
    print(f"\nActualizando estado (state) para '{char_name}'...")
    soul_data = llm.get_character_soul(char_name)
    if not soul_data or "compressed" not in soul_data:
        print("No se pudieron leer los datos del alma.")
        return
        
    comp = soul_data["compressed"]
    char_dir = llm.state_manager._base_dir / char_name
    state_dir = char_dir / "state"
    p_state_path = state_dir / "personality_state.json"
    
    p_state = {}
    if p_state_path.exists():
        try:
            with open(p_state_path, "r", encoding="utf-8") as f:
                p_state = json.load(f)
        except Exception:
            p_state = {}
            
    summary = comp.get("core_identity", {}).get("summary", "")
    archetype = comp.get("core_identity", {}).get("archetype", "")
    philosophy = comp.get("life_philosophy", "")
    
    base_p = f"Arquetipo: {archetype}\nIdentidad: {summary}\nFilosofía de vida: {philosophy}"
    p_state["base_personality"] = base_p
    p_state["behavior_summary"] = f"Actúa de acuerdo con su arquetipo de {archetype}."
    
    try:
        with open(p_state_path, "w", encoding="utf-8") as f:
            json.dump(p_state, f, ensure_ascii=False, indent=2)
        print(f"  ✓ {p_state_path.name} actualizado con arquetipo e identidad.")
    except Exception as e:
        print(f"Error escribiendo personality_state.json: {e}")

def improve_dna_with_soul(char_name, llm):
    print(f"\nMejorando estructura de DNA para '{char_name}' con datos de la Soul...")
    soul_data = llm.get_character_soul(char_name)
    if not soul_data or "compressed" not in soul_data:
        print("No se encontraron datos del alma.")
        return
        
    comp = soul_data["compressed"]
    char_dir = llm.state_manager._base_dir / char_name
    dna_dir = char_dir / "dna"
    
    # 1. identity.json
    ident_path = dna_dir / "identity.json"
    if ident_path.exists():
        try:
            with open(ident_path, "r", encoding="utf-8") as f:
                ident = json.load(f)
            orig_bg = ident.get("background", "")
            summary = comp.get("core_identity", {}).get("summary", "")
            memories_str = ", ".join(comp.get("core_memories", []))
            
            ident["background"] = f"{orig_bg}\n\n[Evolución del Alma]: {summary}\nRecuerdos clave: {memories_str}".strip()
            
            with open(ident_path, "w", encoding="utf-8") as f:
                json.dump(ident, f, ensure_ascii=False, indent=2)
            print("  ✓ identity.json actualizado (background enriquecido).")
        except Exception as e:
            print(f"Error actualizando identity.json: {e}")

    # 2. personality.json
    pers_path = dna_dir / "personality.json"
    if pers_path.exists():
        try:
            with open(pers_path, "r", encoding="utf-8") as f:
                pers = json.load(f)
                
            flaws = pers.get("flaws", [])
            scars = comp.get("emotional_scars", [])
            shame = comp.get("secret_shame", "")
            for s in scars:
                if s not in flaws:
                    flaws.append(s)
            if shame and shame not in flaws:
                flaws.append(shame)
            pers["flaws"] = flaws
            
            mots = pers.get("motivations", [])
            desires = comp.get("hidden_desires", [])
            for d in desires:
                if d not in mots:
                    mots.append(d)
            pers["motivations"] = mots
            
            traits = pers.get("traits", [])
            arch = comp.get("core_identity", {}).get("archetype", "")
            if arch and arch not in traits:
                traits.append(f"Actúa como {arch}")
            biases = comp.get("behavior_biases", [])
            for b in biases:
                if b not in traits:
                    traits.append(b)
            pers["traits"] = traits
            
            with open(pers_path, "w", encoding="utf-8") as f:
                json.dump(pers, f, ensure_ascii=False, indent=2)
            print("  ✓ personality.json actualizado (rasgos, defectos y motivaciones evolucionadas).")
        except Exception as e:
            print(f"Error actualizando personality.json: {e}")

    # 3. speech.json
    speech_path = dna_dir / "speech.json"
    if speech_path.exists():
        try:
            with open(speech_path, "r", encoding="utf-8") as f:
                sp = json.load(f)
                
            s_bias = comp.get("speech_bias", {})
            style = s_bias.get("style", "")
            quirks = s_bias.get("quirks", [])
            
            if style:
                orig_style = sp.get("style", "")
                sp["style"] = f"{orig_style} (Influencia: {style})".strip()
                
            orig_quirks = sp.get("quirks", [])
            for q in quirks:
                if q not in orig_quirks:
                    orig_quirks.append(q)
            sp["quirks"] = orig_quirks
            
            with open(speech_path, "w", encoding="utf-8") as f:
                json.dump(sp, f, ensure_ascii=False, indent=2)
            print("  ✓ speech.json actualizado (estilo de habla y particularidades).")
        except Exception as e:
            print(f"Error actualizando speech.json: {e}")


def select_character(llm):
    chars = llm.list_characters()
    if not chars:
        print("No hay personajes disponibles. Crea uno primero con example_ai_builder.py")
        return None

    print("\nPersonajes disponibles:")
    for i, name in enumerate(chars, 1):
        soul = " [ALMA]" if llm.has_character_soul(name) else ""
        print(f"  {i}. {name}{soul}")

    while True:
        try:
            sel = input("\nSelecciona el número del personaje (o nombre): ").strip()
            if not sel:
                return None
            if sel.isdigit():
                idx = int(sel) - 1
                if 0 <= idx < len(chars):
                    return chars[idx]
            elif sel in chars:
                return sel
            print(f"Opción inválida. Elige 1-{len(chars)} o un nombre.")
        except (ValueError, IndexError):
            print("Entrada inválida.")


def progress_printer(progress, stage):
    bar = "█" * (progress // 5) + "░" * (20 - progress // 5)
    
    # Detect if it's an event or reflection to keep it in the log history
    is_log = False
    if "Age" in stage and "Processing life" not in stage:
        is_log = True
    elif "↳" in stage or "[Reflection" in stage or "[Belief" in stage or "[Coping" in stage:
        is_log = True

    if is_log:
        # Print event on a new line so it forms a readable history
        print(f"\r{' ' * 100}\r  [{bar}] {progress:3d}%  {stage}")
    else:
        # Normal progress update, overwrite the line
        print(f"\r  [{bar}] {progress:3d}%  {stage:<80}", end="", flush=True)
        
    if progress == 100:
        print()

def show_psychology_profile(llm, name):
    """Perfil completo: CoreIdentity → Genome → Psychology → Persona → Soul."""
    cm = llm.state_manager
    psych_mgr = getattr(cm, '_psychology_manager', None)

    print(f"\n{'='*58}")
    print(f"  PERFIL PSICOLÓGICO: {name}")
    print(f"{'='*58}")

    # ── 0. CORE IDENTITY ─────────────────────────────────────
    core_id = getattr(cm, '_core_identity', None)
    if core_id:
        print(f"\n  [CORE IDENTITY — Filtro de interpretación]")
        if core_id.core_fears:
            print(f"    Miedos: {', '.join(core_id.core_fears[:4])}")
        if core_id.core_desires:
            print(f"    Deseos: {', '.join(core_id.core_desires[:4])}")
        if core_id.self_narrative:
            print(f"    Auto-narrativa: \"{core_id.self_narrative[:120]}\"")

        # Contradicciones internas
        conflicts = core_id.derive_contradictions()
        if conflicts:
            print(f"    Conflictos internos:")
            for c in conflicts[:3]:
                print(f"      • {c}")

        # Creencias sobre sí mismo dañadas
        low_beliefs = {k: v for k, v in core_id.self_beliefs.items() if v < 0.4}
        if low_beliefs:
            print(f"    Creencias dañadas:")
            for k, v in low_beliefs.items():
                print(f"      {k.replace('_',' ').capitalize()}: {v:.2f}")

        # Sesgos de interpretación activos
        biases_high = {k: v for k, v in core_id.interpretation_biases.items() if v > 0.6}
        if biases_high:
            print(f"    Sesgos activos: {', '.join(biases_high.keys())}")

        # Memory loss
        if getattr(core_id, 'memory_loss_start_age', 0) > 0:
            print(f"    Amnesia: No recuerda antes de los {core_id.memory_loss_start_age} años")

    # ── 1. GENOME ─────────────────────────────────────────────
    genome = getattr(cm, '_genome', None)
    if genome:
        print(f"\n  [GENOME — Temperamento innato]")
        high = [(k, v) for k, v in genome.__dict__.items()
                if isinstance(v, (int, float)) and v > 0.6]
        low = [(k, v) for k, v in genome.__dict__.items()
               if isinstance(v, (int, float)) and v < 0.4]
        if high:
            print(f"    Alta predisposición: {', '.join(f'{k} ({v:.2f})' for k, v in high[:5])}")
        if low:
            print(f"    Baja predisposición: {', '.join(f'{k} ({v:.2f})' for k, v in low[:5])}")

    # ── 2. PSYCHOLOGY ─────────────────────────────────────────
    if psych_mgr and psych_mgr.psychology:
        ps = psych_mgr.psychology
        bf = ps.current_big_five
        print(f"\n  [PSYCHOLOGY — Estado emergente]")
        print(f"    Big Five: O={bf.get('openness',0):.2f} C={bf.get('conscientiousness',0):.2f} "
              f"E={bf.get('extraversion',0):.2f} A={bf.get('agreeableness',0):.2f} "
              f"N={bf.get('neuroticism',0):.2f}")
        print(f"    Apego: {ps.attachment_style.capitalize()}")
        unsatisfied = [k for k, v in ps.needs.items() if v < 0.35]
        if unsatisfied:
            print(f"    Necesidades activas: {', '.join(unsatisfied)}")
        if ps.active_wounds:
            print(f"    Heridas: {ps.active_wounds[0][:80]}")
        if ps.active_conflicts:
            print(f"    Conflictos: {ps.active_conflicts[0][:80]}")
        print(f"    Visión del mundo: optimismo={ps.worldview.get('optimism',0):.2f} "
              f"confianza={ps.worldview.get('trust_in_people',0):.2f}")

    # ── 3. PERSONA ────────────────────────────────────────────
    if psych_mgr and psych_mgr.persona:
        p = psych_mgr.persona
        print(f"\n  [PERSONA — Expresión actual]")
        print(f"    Estilo: {p.speech_style} | Verborrea: {p.verbosity:.2f} | "
              f"Sarcasmo: {p.sarcasm_tendency:.2f}")
        print(f"    Calidez: {p.warmth:.2f} | Defensividad: {p.defensiveness:.2f}")
        if p.humor_style != "none":
            print(f"    Humor: {p.humor_style.replace('_', ' ')} ({p.humor_frequency:.0%})")
        print(f"    Distancia emocional: {p.emotional_distance:.2f}")

    # ── 4. EMOTION ────────────────────────────────────────────
    if psych_mgr and psych_mgr.emotional:
        em = psych_mgr.emotional
        print(f"\n  [EMOCIÓN]")
        print(f"    Estado: {em.dominant_emotion.capitalize()} "
              f"(valencia={em.valence:.2f}, activación={em.arousal:.2f})")

    # ── 5. TURNING POINTS ─────────────────────────────────────
    if psych_mgr and hasattr(psych_mgr, '_turning_points') and psych_mgr._turning_points:
        print(f"\n  [TURNING POINTS — {len(psych_mgr._turning_points)} momentos que redefinieron su identidad]")
        for tp in psych_mgr._turning_points[-3:]:
            age = getattr(tp, 'age', '?')
            sign = "+" if getattr(tp, 'positive', True) else "-"
            meaning = getattr(tp, 'meaning_assigned', '')
            event = getattr(tp, 'event', '')[:100]
            print(f"    [{sign}] Age {age}: {event}")
            if meaning:
                print(f"         → {meaning}")

    # ── 6. SOUL ───────────────────────────────────────────────
    has_soul = llm.has_character_soul(name)
    if has_soul:
        soul_data = llm.get_character_soul(name)
        if soul_data:
            compressed = soul_data.get("compressed", {})
            archetype = compressed.get("core_identity", {}).get("archetype", "") if isinstance(compressed, dict) else ""
            philosophy = compressed.get("life_philosophy", "") if isinstance(compressed, dict) else ""
            print(f"\n  [ALMA]")
            if archetype:
                print(f"    Arquetipo: {archetype}")
            if philosophy:
                print(f"    Filosofía: {philosophy[:100]}")
            beliefs = soul_data.get("beliefs", [])
            if beliefs:
                print(f"    Creencias formadas: {len(beliefs)}")
                for b in beliefs[:3]:
                    print(f"      • {b.get('content', '')[:80]}")

    print(f"\n{'='*58}\n")


def main():
    print("==========================================")
    print("     SOUL GENERATOR (vtool_llama v0.3)    ")
    print("==========================================")
    print("  Arquitectura v2:")
    print("  Genome → Core Identity → Soul →")
    print("  Psychology → Persona → Prompt")
    print("  El personaje NO nace siendo alguien.")
    print("  Se CONVIERTE por lo que vive.\n")

    try:
        llm = VToolLlama(auto_load=True)
    except Exception as e:
        print(f"\nError cargando modelo: {e}")
        return

    char_name = select_character(llm)
    if not char_name:
        return

    force = False
    if llm.has_character_soul(char_name):
        print(f"\n'{char_name}' ya tiene alma generada.")
        resp = input("  [r] Regenerar  |  [v] Ver perfil  |  [c] Chatear  |  Enter = salir: ").strip().lower()
        if resp == 'r':
            force = True
        elif resp == 'v':
            llm.load_character(char_name)
            show_psychology_profile(llm, char_name)
            resp2 = input("¿Chatear? (s/N): ").strip().lower()
            if resp2 == 's':
                run_chat(llm, char_name)
            return
        elif resp == 'c':
            llm.load_character(char_name)
            run_chat(llm, char_name)
            return
        else:
            return
    else:
        print(f"\n'{char_name}' NO tiene alma. Generar una ahora.")
        resp = input("¿Generar alma? (s/N): ").strip().lower()
        if resp != 's':
            return

    # Preguntar por Modo Auto Respuestas
    resp_auto = input("¿Activar modo auto respuestas (60s de inactividad -> autocompletado)? (s/N): ").strip().lower()
    auto_response = resp_auto == 's'

    # Preguntar por Modo Interactivo
    resp_inter = input("¿Usar Modo Interactivo (intervenir año a año)? (s/N): ").strip().lower()
    interactive = resp_inter == 's'

    # Definir callback interactivo para la CLI
    def cli_interactive_callback(year, year_events):
        # Caso 1: Consulta de aclaración por la IA
        if year_events and len(year_events) == 1 and year_events[0].get("type") == "query":
            q_data = year_events[0]
            print(f"\n\n[?] CONSULTA DEL LIFE DIRECTOR (Edad {year} años):")
            print(f"    Evento propuesto: {q_data['event'].get('description')}")
            print(f"    Pregunta de la IA: {q_data.get('query')}")
            ans = get_input("    Tu respuesta (orquestador): ", default="Tu elige", auto_enabled=auto_response).strip()
            return ans or "Desconocido"

        # Caso 2: Intercepción de evento de caos aleatorio
        elif year_events and len(year_events) == 1 and year_events[0].get("type") == "chaos_roll":
            c_data = year_events[0]["event"]
            print(f"\n\n[⚡] EVENTO DE CAOS ALEATORIO (Edad {year} años, Tipo: {c_data.get('type')}, Importancia: {c_data.get('importance')}):")
            print(f"    Propuesta inicial: {c_data.get('description')}")
            ans = get_input("    Modifica/detalla el evento (o presiona Enter para usar la propuesta): ", default="continue", auto_enabled=auto_response).strip()
            if ans:
                return ans
            return "continue"

        # Caso 3: Fin de año normal
        print(f"\n\n--- Fin del año {year} (Edad {year} años) ---")
        if year_events:
            print("Eventos ocurridos este año:")
            for ev in year_events:
                print(f"  - [{ev.get('type')}] {ev.get('description')} (Importancia: {ev.get('importance')})")
        else:
            print("No ocurrieron eventos significativos este año.")
            
        while True:
            sel = get_input("\n[c] Continuar | [i] Inyectar evento | [s] Saltar hasta el final: ", default="c", auto_enabled=auto_response).strip().lower()
            if sel == 'c':
                return "continue"
            elif sel == 's':
                llm._soul_generator._interactive_mode = False
                return "skip"
            elif sel == 'i':
                ev_type = get_input("Tipo de evento (trauma/romantic/family/etc.): ", default="trauma", auto_enabled=auto_response).strip().lower()
                ev_desc = get_input("Descripción del evento: ", default="Tu elige", auto_enabled=auto_response).strip()
                if not ev_desc:
                    print("Descripción vacía. Inténtalo de nuevo.")
                    continue
                return f"inject:{ev_type}:{ev_desc}"
            print("Opción inválida.")

    # Cargar personaje para poder consultar su identidad en el modo automático
    llm.load_character(char_name)
    identity = llm.state_manager.identity
    personality = llm.state_manager.personality_dna

    # Validar edad en DNA
    age_str = str(getattr(identity, "age", ""))
    age_int = None
    try:
        first_word = age_str.strip().split()[0]
        if first_word.isdigit():
            age_int = int(first_word)
    except (ValueError, IndexError):
        pass

    max_age_years = None
    if age_int is None:
        print(f"\n[!] La edad del personaje '{char_name}' es desconocida o inválida en su DNA ('{age_str}').")
        while True:
            user_age_str = get_input("Ingresa la edad/límite de años a simular para la generación de alma (ej. 25) [25]: ", default="25", auto_enabled=auto_response).strip()
            if user_age_str.isdigit():
                max_age_years = int(user_age_str)
                if 1 <= max_age_years <= 100:
                    break
                else:
                    print("Por favor, ingresa un número de años válido entre 1 y 100.")
            else:
                print("Por favor, ingresa un número entero válido.")

    # Contexto de Mundo
    print("\n--- Configuración de Construcción de Mundo (World Building) ---")
    resp_auto_world = get_input("¿Deseas que la IA configure automáticamente el contexto del mundo basándose en el personaje? (s/N) [n]: ", default="n", auto_enabled=auto_response).strip().lower()
    auto_world = resp_auto_world == 's'
    
    world_type = "real"
    country = "US"
    birth_year = 2000
    use_historical_context = False
    fictional_lore_reference = ""
    economy = "stable"
    family_income = "middle_class"
    world_description = ""
    
    if auto_world:
        print("\n  [IA] Analizando personaje y diseñando el contexto del mundo automáticamente...")
        traits_str = ", ".join(personality.traits) if personality else ""
        flaws_str = ", ".join(personality.flaws) if personality else ""
        motivations_str = ", ".join(personality.motivations) if personality else ""
        
        prompt = (
            f"Analiza la identidad y antecedentes de este personaje para deducir el contexto del mundo en el que nació y creció.\n\n"
            f"Nombre: {getattr(identity, 'name', char_name)}\n"
            f"Rol: {getattr(identity, 'role', 'Desconocido')}\n"
            f"Antecedentes: {getattr(identity, 'background', '')}\n"
            f"Escenario: {getattr(identity, 'scenario', '')}\n"
            f"Rasgos: {traits_str}\n"
            f"Motivaciones: {motivations_str}\n"
            f"Defectos/Miedos: {flaws_str}\n\n"
            "Determina de forma lógica, coherente y detallada los siguientes parámetros de construcción de mundo (world building):\n"
            "1. world_type: Debe ser 'real' (si es el mundo real de la Tierra, ej: EE.UU., Cuba, Europa, etc.) o 'fictional' (si es un mundo de fantasía, ciencia ficción, o un reino inventado).\n"
            "2. country: El país, región, continente o reino de nacimiento (ej. 'Cuba', 'US', 'Middle-earth', 'Reino de Elria').\n"
            "3. birth_year: El año de nacimiento que mejor encaje con la tecnología o era del trasfondo (ej. 1975, 2000, o un año relativo en mundos fantásticos).\n"
            "4. use_historical_context: (Solo si world_type es 'real') true si queremos usar eventos históricos reales de la región/país durante la vida de este personaje para moldear sus recuerdos y vivencias (ej. la crisis de Cuba de 1990, la guerra fría, la caída del muro de Berlín), o false si preferimos eventos más generales.\n"
            "5. fictional_lore_reference: (Solo si world_type es 'fictional') Una descripción de lore, referencia a un libro conocido (ej. 'El Señor de los Anillos', 'Cosmere'), o resumen histórico de ese mundo ficticio durante los años de su vida para basar los eventos.\n"
            "6. economy: Situación económica del entorno en el que nació (stable, poor, crisis).\n"
            "7. family_income: Ingresos de su familia al nacer (poor, middle_class, rich).\n"
            "8. world_description: Breve descripción de la sociedad, tecnología o leyes especiales del entorno (ej. 'Magia prohibida por la inquisición', 'Distopía cyberpunk corporativa', 'Crisis económica y desabastecimiento general').\n\n"
            "Responde UNICAMENTE con un objeto JSON con el siguiente formato exacto sin formatear con markdown ni bloques de código (solo el JSON puro):\n"
            "{\n"
            '  "world_type": "real" o "fictional",\n'
            '  "country": "...",\n'
            '  "birth_year": <int>,\n'
            '  "use_historical_context": <bool>,\n'
            '  "fictional_lore_reference": "...",\n'
            '  "economy": "stable" o "poor" o "crisis",\n'
            '  "family_income": "poor" o "middle_class" o "rich",\n'
            '  "world_description": "..."\n'
            "}\n"
        )
        
        try:
            result = llm._model_manager.generate(
                messages=[
                    {"role": "system", "content": "Eres un asistente experto en creación de mundos y perfiles de personajes. Responde únicamente con JSON puro sin formato markdown."},
                    {"role": "user", "content": prompt}
                ],
                stream=False,
                max_tokens=1024,
                temperature=0.7,
            )
            response_text = result["choices"][0]["message"].get("content", "")
            start_idx = response_text.find("{")
            end_idx = response_text.rfind("}") + 1
            if start_idx != -1 and end_idx > start_idx:
                parsed = json.loads(response_text[start_idx:end_idx])
                world_type = parsed.get("world_type", "real")
                country = parsed.get("country", "US")
                birth_year = int(parsed.get("birth_year", 2000))
                use_historical_context = bool(parsed.get("use_historical_context", False))
                fictional_lore_reference = parsed.get("fictional_lore_reference", "")
                economy = parsed.get("economy", "stable")
                family_income = parsed.get("family_income", "middle_class")
                world_description = parsed.get("world_description", "")
            else:
                print("No se pudo parsear el JSON de la respuesta. Usando configuración manual.")
                auto_world = False
        except Exception as e:
            print(f"Error generando configuración automática: {e}. Usando configuración manual.")
            auto_world = False

    if not auto_world:
        world_type = get_input("¿El personaje vive en el mundo real o en un mundo ficticio/fantasía? (real/fictional) [real]: ", default="real", auto_enabled=auto_response).strip().lower() or "real"
        if world_type not in ("real", "fictional"):
            world_type = "real"
            
        if world_type == "real":
            country = get_input("País/Región de origen (ej. Cuba, US, México) [US]: ", default="US", auto_enabled=auto_response).strip() or "US"
            
            birth_year_str = get_input("Año histórico de nacimiento (ej. 1990, 2000) [2000]: ", default="2000", auto_enabled=auto_response).strip()
            birth_year = int(birth_year_str) if birth_year_str.isdigit() else 2000
            
            use_hist_str = get_input("¿Deseas usar la situación histórica real del país/región en cuestión? (s/N) [n]: ", default="n", auto_enabled=auto_response).strip().lower()
            use_historical_context = use_hist_str == 's'
            fictional_lore_reference = ""
        else:
            country = get_input("Reino/Mundo/Región ficticia (ej. Middle-earth, Alera, Fantasía) [Fantasía]: ", default="Fantasía", auto_enabled=auto_response).strip() or "Fantasía"
            
            birth_year_str = get_input("Año o era de nacimiento en ese mundo ficticio (ej. 1000) [1000]: ", default="1000", auto_enabled=auto_response).strip()
            birth_year = int(birth_year_str) if birth_year_str.isdigit() else 1000
            
            fictional_lore_reference = get_input("Referencia de lore, libro conocido o descripción del lore de esa era [Ninguna]: ", default="", auto_enabled=auto_response).strip()
            use_historical_context = False
            
        if world_type == "real" and use_historical_context:
            print("\n[Info] La situación económica general del país se deducirá automáticamente del contexto histórico real de esa época.")
            economy = "historical (determined by era)"
        else:
            economy = get_input("Situación económica del país/mundo (stable, poor, crisis) [stable]: ", default="stable", auto_enabled=auto_response).strip() or "stable"
            
        family_income = get_input("Nivel de ingresos familiares (poor, middle_class, rich) [middle_class]: ", default="middle_class", auto_enabled=auto_response).strip() or "middle_class"
        world_description = get_input("Descripción y leyes especiales del mundo (ej. distopía cyberpunk, magia prohibida) [Ninguna]: ", default="", auto_enabled=auto_response).strip()

    # Mostrar la configuración establecida
    print(f"\n==========================================")
    print(f"  CONFIGURACIÓN DE MUNDO ESTABLECIDA:")
    print(f"==========================================")
    print(f"  - Tipo de Mundo: {'MUNDO REAL' if world_type == 'real' else 'MUNDO FICTICIO/FANTASÍA'}")
    print(f"  - País/Región/Reino: {country}")
    print(f"  - Año de Nacimiento: {birth_year}")
    if world_type == "real":
        print(f"  - Usar Contexto Histórico: {'Sí (Los recuerdos se basarán en hechos históricos reales de la era)' if use_historical_context else 'No'}")
    else:
        print(f"  - Referencia de Lore: {fictional_lore_reference or 'Ninguna'}")
    print(f"  - Situación Económica: {economy}")
    print(f"  - Nivel de Ingresos Familiares: {family_income}")
    print(f"  - Leyes/Descripción del Mundo: {world_description or 'Ninguna'}")
    print(f"==========================================\n")

    start_age_years_str = get_input("Edad de inicio de simulación de vida (0 para nacer de nuevo, ej. 24) [0]: ", default="0", auto_enabled=auto_response).strip()
    start_age_years = int(start_age_years_str) if start_age_years_str.isdigit() else 0

    default_memory_loss_age = str(start_age_years)
    memory_loss_start_age_str = get_input(f"Edad límite de pérdida de memoria consciente / amnesia (ej. {start_age_years}) [{default_memory_loss_age}]: ", default=default_memory_loss_age, auto_enabled=auto_response).strip()
    memory_loss_start_age = int(memory_loss_start_age_str) if memory_loss_start_age_str.isdigit() else start_age_years

    resp_history = get_input("¿Deseas guardar el historial completo de eventos cronológicos en un archivo JSON (life_events.json)? (S/n) [s]: ", default="s", auto_enabled=auto_response).strip().lower()
    save_events_history = resp_history != 'n'

    # Confirmar
    print(f"\n  El alma se genera simulando la vida MES A MES.")
    print(f"  Con LLM real puede tomar MINUTOS O HORAS.")
    print(f"  Guarda checkpoints, se puede reanudar.\n")
    resp = input(f"¿Generar alma para '{char_name}'? (s/N): ").strip().lower()
    if resp != 's':
        print("Cancelado.")
        return

    print(f"\nGenerando alma para '{char_name}'...")
    print("(Ctrl+C para pausar)\n")

    try:
        result = llm.generate_character_soul(
            character_name=char_name,
            force_regenerate=force,
            seed=None,
            progress_callback=progress_printer,
            country=country,
            birth_year=birth_year,
            economy=economy,
            family_income=family_income,
            world_description=world_description,
            start_age_years=start_age_years,
            memory_loss_start_age=memory_loss_start_age,
            interactive_mode=interactive,
            interactive_callback=cli_interactive_callback if interactive else None,
            world_type=world_type,
            use_historical_context=use_historical_context,
            fictional_lore_reference=fictional_lore_reference,
            max_age_years=max_age_years,
            save_events_history=save_events_history,
        )

        print(f"\n  Alma generada con {result.get('events_generated', '?')} eventos.")
        if save_events_history:
            print(f"  [Historial] Timeline de eventos detallada en JSON guardada en: {llm.state_manager._base_dir / char_name / 'memory' / 'life_events.json'}")
        if result.get('genome'):
            print(f"  Genome: {sum(1 for v in result['genome'].values() if isinstance(v, (int,float)) and v > 0.6)} ejes altos")

    except KeyboardInterrupt:
        print("\n\n  Pausado. El progreso se guardó. Reanuda ejecutando otra vez.")
        return
    except Exception as e:
        print(f"\nError: {e}")
        return

    # Preguntar si desea actualizar el directorio state
    resp_state = input(f"\n¿Deseas actualizar los valores de estado (state) del personaje '{char_name}' con los datos del alma? (s/N): ").strip().lower()
    if resp_state == 's':
        update_character_state_with_soul(char_name, llm)

    # Preguntar si desea mejorar el DNA con los datos del alma
    resp_dna = input(f"¿Deseas mejorar la estructura del DNA de '{char_name}' con los nuevos datos de la Soul (evolucionar)? (s/N): ").strip().lower()
    if resp_dna == 's':
        improve_dna_with_soul(char_name, llm)

    # Cargar (esto construye el base_soul.state KV Cache si corresponde) y mostrar perfil completo
    print("\nCargando personaje con alma y compilando KV cache...")
    llm.load_character(char_name)
    show_psychology_profile(llm, char_name)

    resp = input(f"¿Iniciar chat con '{char_name}' (con alma + psicología + persona)? (s/N): ").strip().lower()
    if resp == 's':
        run_chat(llm, char_name)


def run_chat(llm, name):
    cm = llm.state_manager
    psych_mgr = getattr(cm, '_psychology_manager', None)

    print(f"\n--- {name.capitalize()} (Arquitectura v2) ---")
    print("  /psych    — perfil psicológico completo")
    print("  /persona  — capa de expresión actual")
    print("  /why      — \"por qué soy como soy\" (narrativa psicológica)")
    print("  /timeline — línea de vida con turning points y memorias")
    print("  /state    — estado completo del agente")
    print("  /mem      — guardar memoria")
    print("  salir     — terminar\n")

    while True:
        try:
            user = input("Tú: ")
            if user.strip().lower() in ("salir", "exit", "quit"):
                break
            if not user.strip():
                continue

            if user.strip() == "/psych":
                show_psychology_profile(llm, name)
                continue
            if user.strip() == "/persona":
                if psych_mgr and psych_mgr.persona:
                    print(psych_mgr.get_persona_block())
                continue
            if user.strip() == "/why":
                if psych_mgr:
                    print(psych_mgr.get_why_block())
                else:
                    print("(No hay psicología activa)")
                continue
            if user.strip() == "/timeline":
                if psych_mgr:
                    print(psych_mgr.get_timeline_block())
                else:
                    print("(No hay línea de vida disponible)")
                continue
            if user.strip() == "/state":
                info = llm.get_state_info()
                import json
                print(json.dumps(info, ensure_ascii=False, indent=2))
                continue

            print(f"\n{name.capitalize()}:", end=" ", flush=True)
            for chunk in llm.stream_chat(user):
                print(chunk, end="", flush=True)
            print()

        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    main()
