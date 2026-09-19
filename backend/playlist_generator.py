import hashlib
import os
import random
import time
from typing import List, Optional

from evaluation import evaluate_playlist
from user_profile_encoder import cosine_similarity

try:
    from spotify_service_fixed import normalize_artist_name, track_fingerprint
except Exception:  # pragma: no cover
    def normalize_artist_name(name: str) -> str:  # type: ignore[misc]
        return str(name or "").split(",")[0].strip().lower()

    def track_fingerprint(name: str, artist: str) -> str:  # type: ignore[misc]
        return f"{str(name or '').strip().lower()}|{normalize_artist_name(artist)}"

try:
    from config.scoring_config import RANKING as _RCFG
    _SCORING_CFG_AVAILABLE = True
except ImportError:
    _SCORING_CFG_AVAILABLE = False

try:
    from explanation_engine import generate_playlist_explanations
except Exception as _explanation_err:  # pragma: no cover
    generate_playlist_explanations = None  # type: ignore[assignment,misc]
    print(f"[playlist_generator] explanation_engine unavailable: {_explanation_err}")

try:
    from exploration_engine import inject_exploration_tracks
except Exception as _exploration_err:  # pragma: no cover
    inject_exploration_tracks = None  # type: ignore[assignment,misc]
    print(f"[playlist_generator] exploration_engine unavailable: {_exploration_err}")

try:
    from track_graph import TrackGraph
except Exception as _tg_err:  # pragma: no cover
    TrackGraph = None  # type: ignore[assignment,misc]
    print(f"[playlist_generator] track_graph unavailable: {_tg_err}")

try:
    from playlist_flow_engine import reorder_for_flow as _reorder_for_flow
except Exception as _flow_err:  # pragma: no cover
    _reorder_for_flow = None  # type: ignore[assignment,misc]
    print(f"[playlist_generator] playlist_flow_engine unavailable: {_flow_err}")

try:
    from flow_evaluation import evaluate_flow as _evaluate_flow, is_flow_debug_enabled
except Exception as _fe_err:  # pragma: no cover
    _evaluate_flow = None  # type: ignore[assignment,misc]
    def is_flow_debug_enabled() -> bool: return False  # type: ignore[misc]
    print(f"[playlist_generator] flow_evaluation unavailable: {_fe_err}")

# ── Runtime trace (zero overhead when disabled) ───────────────────────────
try:
    from debug.runtime_trace import (
        PipelineTrace, is_trace_enabled,
        trace_exploration, trace_flow_reorder,
        log_trace_if_enabled,
    )
    _TRACE_AVAILABLE = True
except ImportError:
    _TRACE_AVAILABLE = False

# ── Monitoring (zero overhead when disabled) ──────────────────────────────
try:
    from monitoring.metrics_store import get_store as _get_metrics_store, is_monitoring_enabled
    _MONITORING_AVAILABLE = True
except ImportError:
    _MONITORING_AVAILABLE = False

# ── Session intent conditioning ───────────────────────────────────────────
try:
    from config.session_intents import (
        resolve_intent_with_confidence as _resolve_intent_with_confidence,
        IntentProfile, IntentResolution,
        adaptive_gate_filter as _adaptive_gate_filter,
        relaxed_exploration_ratio as _relaxed_exploration_ratio,
        relax_gate as _relax_gate,
    )
    _INTENTS_AVAILABLE = True
except ImportError:
    _INTENTS_AVAILABLE = False

try:
    from contracts.pipeline_integrity import PipelineStage
    _PIPELINE_INTEGRITY_AVAILABLE = True
except ImportError:
    class PipelineStage:  # type: ignore[no-redef]
        CANDIDATE_RETRIEVAL = None
        POST_INTENT_GATE = None
        ADAPTIVE_RELAXATION = None
        EXPLORATION_INJECTION = None
        SEQUENCING_PRECONDITION = None
        FINAL_ORDERED_PLAYLIST = None
    _PIPELINE_INTEGRITY_AVAILABLE = False


def _validate_pipeline_stage(stage, **kwargs) -> None:
    """Advisory-only runtime integrity validation for pipeline stage outputs."""
    if not _PIPELINE_INTEGRITY_AVAILABLE:
        return
    try:
        stage.validate(emit_warnings=True, **kwargs)
    except Exception:
        pass

FALLBACK_AUDIO_FEATURES = {
    "danceability": 0.5,
    "energy": 0.5,
    "valence": 0.5,
    "acousticness": 0.3,
    "instrumentalness": 0.0,
    "speechiness": 0.05,
}

MOOD_TERMS = {
    "happy": ["happy", "party", "dance", "upbeat", "feel good", "pop"],
    "sad": ["sad", "heartbreak", "lonely", "broken", "slow"],
    "energetic": ["dance", "party", "hit", "banger", "upbeat", "pop", "bhangra"],
    "calm": ["calm", "soft", "chill", "lofi", "acoustic"],
    "focused": ["smooth", "chill", "lofi", "deep", "soft", "study"],
}

PARTY_REJECT_TERMS = [
    "party",
    "dance",
    "kuthu",
    "bhangra",
    "club",
    "hit",
    "anthem",
    "rowdy",
    "vaathi",
    "arabic kuthu",
]

DURATION_TOLERANCE = 0.10
MIN_DURATION_TRACK_MS = 60_000
FALLBACK_DURATION_MS = 180_000

CURATED_FAMILIAR_SEEDS = {
    "india_tamil": [
        ("Vaathi Coming", "Anirudh Ravichander, Gana Balachandar", 78, 225000),
        ("Arabic Kuthu", "Anirudh Ravichander, Jonita Gandhi", 76, 279000),
        ("Rowdy Baby", "Dhanush, Dhee", 74, 281000),
        ("Machi Open the Bottle", "Yuvan Shankar Raja, Mano, Premgi Amaren", 70, 287000),
        ("Why This Kolaveri Di", "Dhanush, Anirudh Ravichander", 72, 260000),
        ("Enjoy Enjaami", "Dhee, Arivu", 68, 279000),
        ("Google Google", "Harris Jayaraj, Vijay, Andrea Jeremiah", 66, 367000),
        ("Appadi Podu", "KK, Anuradha Sriram", 65, 292000),
        ("Aalaporan Tamizhan", "A. R. Rahman, Kailash Kher, Sathya Prakash, Deepak", 69, 325000),
        ("Mersal Arasan", "G. V. Prakash Kumar, Naresh Iyer, Sharanya Srinivas", 67, 256000),
        ("Thalli Pogathey", "A. R. Rahman, Sid Sriram, Aaryan Dinesh Kanagaratnam", 73, 267000),
        ("Nenjukkul Peidhidum", "Harris Jayaraj, Hariharan, Devan, V. V. Prasanna", 71, 356000),
        ("Yathe Yathe", "G. V. Prakash Kumar, Vijay Yesudas", 64, 330000),
        ("Kalasala Kalasala", "Thaman S, L. R. Eswari, T. Rajendar", 68, 250000),
        ("Rakita Rakita Rakita", "Anirudh Ravichander, Dhanush, Deepak Blue", 67, 245000),
        ("Aathichudi", "Vijay Antony, Dinesh Kanagaratnam", 66, 245000),
        ("Kadhal Sadugudu", "A. R. Rahman, S. P. Charan", 65, 274000),
        ("Ennodu Nee Irundhaal", "A. R. Rahman, Sid Sriram, Sunitha Sarathy", 66, 352000),
        ("Oru Manam", "Harris Jayaraj, Karthik, Shashaa Tirupati", 63, 302000),
        ("Kannaana Kanney", "Sid Sriram", 61, 255000),
        ("Anbe Anbe", "Harris Jayaraj, Harish Raghavendra", 64, 332000),
        ("Oru Naalil", "Yuvan Shankar Raja", 62, 346000),
        ("Aagaaya Neelangalil", "Yuvan Shankar Raja, Haricharan", 60, 288000),
        ("Maya Nadhi", "Santhosh Narayanan, Ananthu, Pradeep Kumar", 63, 275000),
        ("Hosanna", "A. R. Rahman, Vijay Prakash, Suzanne D'Mello, Blaaze", 69, 330000),
    ],
    "india_punjabi": [
        ("Brown Munde", "AP Dhillon, Gurinder Gill, Shinda Kahlon", 80, 255000),
        ("Excuses", "AP Dhillon, Gurinder Gill, Intense", 78, 176000),
        ("Pasoori", "Shae Gill, Ali Sethi", 77, 224000),
        ("Lover", "Diljit Dosanjh", 75, 190000),
        ("GOAT", "Diljit Dosanjh", 73, 224000),
        ("Bijlee Bijlee", "Harrdy Sandhu", 72, 168000),
        ("Khaab", "Akhil", 70, 201000),
        ("295", "Sidhu Moose Wala", 74, 270000),
        ("We Rollin", "Shubh", 78, 199000),
        ("Cheques", "Shubh", 76, 193000),
        ("Softly", "Karan Aujla", 74, 168000),
        ("Players", "Badshah, Karan Aujla, Devika Badyal", 72, 179000),
        ("With You", "AP Dhillon", 71, 154000),
        ("Insane", "AP Dhillon, Gurinder Gill, Shinda Kahlon", 70, 198000),
        ("Born To Shine", "Diljit Dosanjh", 69, 205000),
        ("Do You Know", "Diljit Dosanjh", 68, 221000),
        ("Lahore", "Guru Randhawa", 72, 199000),
        ("High Rated Gabru", "Guru Randhawa", 71, 201000),
        ("So High", "Sidhu Moose Wala, Byg Byrd", 69, 232000),
        ("Jatt Da Muqabala", "Sidhu Moose Wala", 66, 218000),
        ("Bapu Zimidar", "Jassi Gill", 65, 181000),
        ("Wang Da Naap", "Ammy Virk", 64, 158000),
        ("Diamond", "Gurnam Bhullar", 66, 224000),
        ("Angreji Beat", "Gippy Grewal, Yo Yo Honey Singh", 68, 203000),
        ("Dil Luteya", "Jazzy B, Apache Indian", 63, 262000),
    ],
    "global_english": [
        ("Blinding Lights", "The Weeknd", 90, 200000),
        ("As It Was", "Harry Styles", 88, 167000),
        ("Levitating", "Dua Lipa", 86, 203000),
        ("good 4 u", "Olivia Rodrigo", 84, 178000),
        ("Anti-Hero", "Taylor Swift", 86, 201000),
        ("Stay", "The Kid LAROI, Justin Bieber", 85, 141000),
        ("Watermelon Sugar", "Harry Styles", 82, 174000),
        ("Heat Waves", "Glass Animals", 84, 239000),
        ("drivers license", "Olivia Rodrigo", 85, 242000),
        ("bad guy", "Billie Eilish", 87, 194000),
        ("BIRDS OF A FEATHER", "Billie Eilish", 84, 210000),
        ("Espresso", "Sabrina Carpenter", 88, 175000),
        ("Please Please Please", "Sabrina Carpenter", 86, 186000),
        ("greedy", "Tate McRae", 83, 131000),
        ("Kill Bill", "SZA", 85, 153000),
        ("Snooze", "SZA", 82, 201000),
        ("Beautiful Things", "Benson Boone", 86, 180000),
        ("Stick Season", "Noah Kahan", 80, 183000),
        ("Chemical", "Post Malone", 79, 184000),
        ("vampire", "Olivia Rodrigo", 82, 220000),
        ("Happier", "Olivia Rodrigo", 79, 175000),
        ("Therefore I Am", "Billie Eilish", 78, 174000),
        ("Circles", "Post Malone", 84, 215000),
        ("abcdefu", "GAYLE", 76, 169000),
        ("Golden Hour", "JVKE", 77, 209000),
    ],
}

CALM_FAMILIAR_SEEDS = {
    "india_tamil": [
        ("New York Nagaram", "A. R. Rahman", 70, 379000),
        ("Munbe Vaa", "Naresh Iyer, Shreya Ghoshal", 72, 358000),
        ("Vaseegara", "Bombay Jayashri", 70, 299000),
        ("Pachai Nirame", "A. R. Rahman, Hariharan", 66, 352000),
        ("The Life of Ram", "Pradeep Kumar", 68, 356000),
        ("Maruvaarthai", "Sid Sriram", 67, 356000),
        ("Kaathalae Kaathalae", "Govind Vasantha, Chinmayi", 66, 194000),
        ("Ennai Saaithaale", "Harris Jayaraj, Karthik, Shreya Ghoshal", 62, 329000),
        ("Nallai Allai", "A. R. Rahman, Sathya Prakash, Chinmayi", 63, 228000),
        ("Kannana Kanne", "Sean Roldan, Sid Sriram", 61, 251000),
        ("Evano Oruvan", "A. R. Rahman, Swarnalatha", 64, 356000),
        ("Vizhigalil Oru Vaanavil", "G. V. Prakash Kumar, Saindhavi", 60, 296000),
        ("Nee Paartha Vizhigal", "Vijay Yesudas, Swetha Mohan", 61, 265000),
        ("Enna Solla Pogirai", "Shankar Mahadevan", 64, 361000),
        ("Idhayathai Yedho Ondru", "Harris Jayaraj, Chinmayi", 59, 235000),
        ("Pogadhe", "Yuvan Shankar Raja", 60, 282000),
        ("Deivangal Ellam", "Yuvan Shankar Raja, Vijay Yesudas", 58, 175000),
    ],
    "india_punjabi": [
        ("Qismat", "Ammy Virk", 65, 244000),
        ("Hawa De Warke", "Ninja", 61, 244000),
        ("Ocean Eyes", "Amrinder Gill", 62, 214000),
        ("Raatan Nu", "Gurnam Bhullar", 60, 242000),
        ("Udaarian", "Satinder Sartaaj", 61, 355000),
        ("Sajjna", "Falak Shabir", 59, 236000),
        ("Mera Yaar", "Kulwinder Billa", 60, 267000),
        ("Kismat 2", "B Praak", 58, 241000),
        ("Rabba", "Rahat Fateh Ali Khan", 57, 261000),
        ("Tere Bina", "Guru Randhawa", 59, 216000),
        ("Ik Tera", "Maninder Buttar", 60, 188000),
        ("Kina Chir", "The PropheC", 56, 226000),
        ("Akhiyan", "Tony Kakkar, Neha Kakkar", 60, 245000),
        ("Tere Bin", "Atif Aslam", 58, 275000),
        ("Pagal", "Gurnam Bhullar", 59, 243000),
        ("Kamli", "Mankirt Aulakh", 57, 232000),
        ("Rabb Wangu", "Jass Manak", 58, 230000),
    ],
    "global_english": [
        ("ocean eyes", "Billie Eilish", 82, 200000),
        ("The Night We Met", "Lord Huron", 80, 208000),
        ("ceilings", "Lizzy McAlpine", 76, 182000),
        ("Skinny Love", "Birdy", 75, 201000),
        ("Let Her Go", "Passenger", 82, 252000),
        ("All Too Well", "Taylor Swift", 78, 329000),
        ("Yellow", "Coldplay", 85, 267000),
        ("What Was I Made For?", "Billie Eilish", 81, 222000),
        ("Sweet", "Cigarettes After Sex", 84, 291000),
        ("Someone You Loved", "Lewis Capaldi", 83, 182000),
        ("When I Was Your Man", "Bruno Mars", 80, 214000),
        ("Fix You", "Coldplay", 79, 296000),
        ("All I Want", "Kodaline", 76, 306000),
        ("Heather", "Conan Gray", 78, 198000),
        ("traitor", "Olivia Rodrigo", 79, 229000),
        ("glimpse of us", "Joji", 80, 233000),
        ("In The Stars", "Benson Boone", 75, 217000),
    ],
}

INTERNAL_DISCOVERY_POOLS = {
    "india_tamil": [
        ("Naa Ready", "Thalapathy Vijay, Anirudh Ravichander, Asal Kolaar", 76, 248000),
        ("Kaavaalaa", "Shilpa Rao, Anirudh Ravichander", 78, 191000),
        ("Makkamishi", "Paal Dabba, Anirudh Ravichander", 74, 252000),
        ("Pathala Pathala", "Kamal Haasan, Anirudh Ravichander", 72, 210000),
        ("Katchi Sera", "Sai Abhyankkar", 70, 182000),
        ("Vaathi Raid", "Arivu, Anirudh Ravichander", 71, 220000),
        ("Kutty Story", "Thalapathy Vijay, Anirudh Ravichander", 69, 244000),
        ("Master The Blaster", "Blaaze, Anirudh Ravichander", 67, 242000),
        ("Aasa Kooda", "Sai Smriti, Sai Abhyankkar", 66, 215000),
        ("Chellamma", "Jonita Gandhi, Anirudh Ravichander", 72, 208000),
        ("Naanga Vera Maari", "Yuvan Shankar Raja, Anurag Kulkarni", 68, 254000),
        ("Manasilaayo", "Malaysia Vasudevan, Yugendran, Anirudh Ravichander", 65, 236000),
        ("Ranjithame", "Thalapathy Vijay, M M Manasi", 73, 247000),
        ("Dippam Dappam", "Anthony Daasan, Anirudh Ravichander", 67, 207000),
        ("Hey Minnale", "Haricharan, Shweta Mohan", 64, 229000),
        ("Naan Naan", "Santhosh Narayanan, Kabilan", 62, 205000),
        ("Neruppu Da", "Arunraja Kamaraj", 66, 217000),
        ("Ulagam Oruvanukka", "Ananthu, Santhosh Narayanan, Gaana Bala", 65, 206000),
        ("Sodakku", "Santhosh Narayanan, Anthony Daasan", 64, 213000),
        ("Surviva", "Yogi B, Mali, Anirudh Ravichander", 63, 223000),
        ("Kannazhaga", "Dhanush, Shruti Haasan, Anirudh Ravichander", 68, 203000),
        ("Selfie Pulla", "Vijay, Sunidhi Chauhan", 66, 248000),
        ("Otha Sollaala", "G. V. Prakash Kumar, Velmurugan", 60, 216000),
        ("Aathi", "Vivek-Mervin, Vishal Dadlani", 61, 232000),
        ("Mental Manadhil", "A. R. Rahman, Jonita Gandhi", 64, 206000),
        ("Naan Sirithal", "Hiphop Tamizha, Kaushik Krish", 58, 224000),
        ("Pakkam Vanthu", "Anirudh Ravichander, Hiphop Tamizha", 59, 238000),
        ("Yendi Yendi", "D. Imman, Vijay Yesudas, Ramya NSK", 57, 282000),
        ("Saarattu Vandiyila", "A. R. Rahman, A. R. Raihanah, Tipu, Nikhita Gandhi", 62, 321000),
        ("Jingunamani", "K. G. Ranjith, Sunidhi Chauhan", 56, 265000),
        ("Kokkarakko", "Vidhu Prathap, Chinmayi", 58, 275000),
        ("Danga Maari Oodhari", "Harris Jayaraj, Dhanush, Marana Gana Viji", 64, 345000),
        ("Adiye", "Dhibu Ninan Thomas, Kapil Kapilan", 63, 272000),
        ("Tum Tum", "Thaman S, Sri Vardhini, Aditi Bhavaraju", 72, 228000),
        ("Megham Karukatha", "Dhanush, Nithya Menen", 66, 291000),
        ("Vaa Vaathi", "G. V. Prakash Kumar, Shweta Mohan", 68, 225000),
        ("Railin Oligal", "A. R. Rahman, Pradeep Kumar, Shakthisree Gopalan", 61, 158000),
        ("Naan Pizhai", "Anirudh Ravichander, Ravi G, Shashaa Tirupati", 64, 244000),
        ("Private Party", "Anirudh Ravichander, Jonita Gandhi", 63, 218000),
        ("Maari Thara Local", "Anirudh Ravichander, Dhanush", 62, 231000),
    ],
    "india_punjabi": [
        ("Rhyme Ain't Done", "Navaan Sandhu", 75, 190000),
        ("Wishes", "Talwiinder", 74, 180000),
        ("25-25", "Arjan Dhillon", 76, 170000),
        ("Old Skool", "Prem Dhillon, Sidhu Moose Wala", 73, 253000),
        ("Teeje Week", "Jordan Sandhu", 71, 190000),
        ("Vibe", "The PropheC", 72, 202000),
        ("Modern Mirza", "Raf Saperra", 70, 206000),
        ("No Safety", "Sukha, Prodgk", 69, 169000),
        ("Obsessed", "Riar Saab, Abhijay Sharma", 77, 190000),
        ("Naah", "Harrdy Sandhu", 71, 181000),
        ("Backbone", "Harrdy Sandhu", 68, 176000),
        ("Kya Baat Ay", "Harrdy Sandhu", 69, 183000),
        ("Hornn Blow", "Harrdy Sandhu", 66, 201000),
        ("5 Taara", "Diljit Dosanjh", 65, 193000),
        ("Patiala Peg", "Diljit Dosanjh", 67, 188000),
        ("Laembadgini", "Diljit Dosanjh", 66, 217000),
        ("Mitran Da Naa", "Jazzy B", 61, 238000),
        ("Gabru", "Jazzy B", 60, 226000),
        ("Lehanga", "Jass Manak", 68, 196000),
        ("Prada", "Jass Manak", 67, 182000),
        ("Suit Suit", "Guru Randhawa, Arjun", 69, 188000),
        ("Qatal", "Guru Randhawa", 64, 184000),
        ("Moon Rise", "Guru Randhawa", 63, 181000),
        ("Na Ja", "Pav Dharia", 65, 183000),
        ("8 Parche", "Baani Sandhu, Gur Sidhu", 66, 196000),
        ("Badnam", "Mankirt Aulakh, DJ Flow", 64, 194000),
        ("Defaulter", "R Nait, Gurlez Akhtar", 62, 218000),
        ("Jhanjar", "Karan Aujla", 60, 191000),
        ("Lalkara", "Diljit Dosanjh", 58, 232000),
        ("Photo", "Karan Sehmbi", 61, 212000),
        ("Schedule", "Tegi Pannu, Manni Sandhu", 72, 174000),
        ("Roots", "Kamal Heer", 73, 226000),
        ("White Brown Black", "Avvy Sra, Karan Aujla, Jaani", 70, 177000),
        ("Chitta Kurta", "Gurlez Akhtar, Karan Aujla", 68, 217000),
        ("Levels", "Sidhu Moose Wala, Sunny Malton", 71, 229000),
        ("Celebrity Killer", "Sidhu Moose Wala, Tion Wayne", 65, 232000),
        ("Yaar Bolda", "Surjit Bindrakhia", 59, 260000),
        ("Naah Goriye", "Harrdy Sandhu, B Praak", 67, 184000),
        ("Suit Punjabi", "Jass Manak", 62, 203000),
        ("Slowly Slowly", "Guru Randhawa, Pitbull", 66, 204000),
    ],
    "global_english": [
        ("Good Luck, Babe!", "Chappell Roan", 84, 218000),
        ("HOT TO GO!", "Chappell Roan", 81, 184000),
        ("Red Wine Supernova", "Chappell Roan", 80, 192000),
        ("Pink Pony Club", "Chappell Roan", 79, 258000),
        ("exes", "Tate McRae", 79, 159000),
        ("you broke me first", "Tate McRae", 78, 169000),
        ("It's ok I'm ok", "Tate McRae", 74, 158000),
        ("Escapism.", "RAYE, 070 Shake", 82, 272000),
        ("Prada", "cassö, RAYE, D-Block Europe", 78, 132000),
        ("Oscar Winning Tears", "RAYE", 69, 201000),
        ("Saturn", "SZA", 79, 187000),
        ("LUNCH", "Billie Eilish", 80, 179000),
        ("Happier Than Ever", "Billie Eilish", 78, 298000),
        ("Nonsense", "Sabrina Carpenter", 77, 164000),
        ("Feather", "Sabrina Carpenter", 79, 186000),
        ("Too Sweet", "Hozier", 83, 251000),
        ("End of Beginning", "Djo", 81, 159000),
        ("Lose Control", "Teddy Swims", 82, 211000),
        ("I Had Some Help", "Post Malone, Morgan Wallen", 84, 178000),
        ("Austin", "Dasha", 75, 171000),
        ("Illusion", "Dua Lipa", 77, 188000),
        ("Training Season", "Dua Lipa", 78, 209000),
        ("Messy", "Lola Young", 72, 260000),
        ("Paint The Town Red", "Doja Cat", 83, 232000),
        ("greedy for your love", "Renee Rapp", 63, 201000),
        ("What It Is (Block Boy)", "Doechii, Kodak Black", 74, 223000),
        ("Agora Hills", "Doja Cat", 76, 265000),
        ("Strangers", "Kenya Grace", 77, 173000),
        ("The Door", "Teddy Swims", 70, 209000),
        ("Fortnight", "Taylor Swift, Post Malone", 80, 228000),
        ("Not Like Us", "Kendrick Lamar", 86, 274000),
        ("A Bar Song (Tipsy)", "Shaboozey", 84, 171000),
        ("360", "Charli xcx", 80, 133000),
        ("Apple", "Charli xcx", 78, 151000),
        ("MILLION DOLLAR BABY", "Tommy Richman", 81, 155000),
        ("Stargazing", "Myles Smith", 79, 172000),
        ("Scared To Start", "Michael Marcagi", 74, 159000),
        ("I Like The Way You Kiss Me", "Artemas", 80, 143000),
        ("Never Lose Me", "Flo Milli", 76, 126000),
        ("Get It Sexyy", "Sexyy Red", 74, 149000),
    ],
}

CALM_DISCOVERY_POOLS = {
    "india_tamil": [
        ("Kannamma", "Santhosh Narayanan, Pradeep Kumar", 64, 245000),
        ("Mazhai Kuruvi", "A. R. Ameen", 66, 348000),
        ("Aaromale", "Alphons Joseph", 67, 346000),
        ("Pookkal Pookkum", "Roop Kumar Rathod, Harini, Andrea Jeremiah, G. V. Prakash Kumar", 65, 395000),
        ("Idhazhin Oram", "Ajesh, Anirudh Ravichander", 62, 205000),
        ("Yaarumilla", "Shweta Mohan, Srinivas", 60, 284000),
        ("Vaan Varuvaan", "Shashaa Tirupati", 61, 256000),
        ("Moongil Thottam", "Abhay Jodhpurkar, Harini", 58, 274000),
        ("Nenjukkule", "A. R. Rahman, Shakthisree Gopalan", 63, 289000),
        ("Yaaro Manathile", "Harris Jayaraj, Bombay Jayashri", 57, 316000),
        ("Maalai Mangum Neram", "Ranina Reddy", 59, 336000),
        ("Yaar Indha Saalai Oram", "G. V. Prakash Kumar, Saindhavi", 57, 306000),
        ("Kanave Kanave", "Anirudh Ravichander", 58, 286000),
        ("Anthaathi", "Chinmayi, Govind Vasantha", 56, 316000),
        ("Thendral Vanthu Theendum Pothu", "Ilaiyaraaja, S. Janaki", 57, 318000),
    ],
    "india_punjabi": [
        ("Sajjan Raazi", "Satinder Sartaaj", 58, 301000),
        ("Ikk Kudi", "Shahid Mallya", 62, 244000),
        ("Mastaani", "B Praak", 57, 238000),
        ("Jannat", "Asees Kaur", 56, 227000),
        ("Roi Na", "Sharry Mann", 61, 228000),
        ("Titliaan", "Afsana Khan", 63, 212000),
        ("Kinna Sona", "Sunil Kamath", 64, 202000),
        ("Mann Bharrya", "B Praak", 66, 190000),
        ("Jind Mahi", "Diljit Dosanjh", 59, 236000),
        ("Sohnea", "Miss Pooja, Millind Gaba", 55, 212000),
        ("Aadat", "Atif Aslam", 63, 260000),
        ("Paani Da Rang", "Ayushmann Khurrana", 64, 239000),
        ("Yaarian", "Harbhajan Mann", 58, 241000),
        ("Main Teri Ho Gayi", "Millind Gaba, Aditi Budhathoki", 60, 216000),
        ("Sohne Lagde", "Sidhu Moose Wala, The PropheC", 59, 235000),
    ],
    "global_english": [
        ("Skin and Bones", "David Kushner", 66, 195000),
        ("Before You Go", "Lewis Capaldi", 78, 216000),
        ("Lose You To Love Me", "Selena Gomez", 75, 206000),
        ("Ghost Town", "Benson Boone", 70, 177000),
        ("Someone To Stay", "Vancouver Sleep Clinic", 62, 224000),
        ("Liability", "Lorde", 69, 172000),
        ("The Scientist", "Coldplay", 80, 309000),
        ("Turning Page", "Sleeping At Last", 64, 255000),
        ("everything i wanted", "Billie Eilish", 80, 245000),
        ("Say You Won't Let Go", "James Arthur", 77, 211000),
        ("My Love Mine All Mine", "Mitski", 76, 138000),
        ("Night Changes", "One Direction", 75, 227000),
        ("Space Song", "Beach House", 78, 321000),
        ("Older", "Sasha Alex Sloan", 68, 191000),
        ("Call Your Mom", "Noah Kahan", 72, 278000),
    ],
}


class PlaylistGenerator:
    recently_served_track_ids = {}
    recent_window_size = 20
    request_serial_by_region = {}

    def __init__(self, spotify_service=None):
        self.spotify_service = spotify_service

    def generate_regional_genome_playlist(
        self,
        user_tracks: List[dict],
        genome: dict,
        cluster_id: int,
        region_key: str,
        playlist_size: int = 30,
        discovery_ratio: float = 0.5,
        target_minutes: Optional[int] = None,
        mood: Optional[str] = None,
        taste_profile: Optional[dict] = None,
        user_embedding=None,
        exploration_ratio: float = 0.0,
        include_explanations: bool = False,
        session_type: Optional[str] = None,
    ) -> dict:
        requested_track_count = max(1, min(int(playlist_size), 50))
        playlist_size = requested_track_count
        duration_diagnostics = None
        if target_minutes:
            playlist_size = max(
                playlist_size,
                self._duration_candidate_track_budget(target_minutes),
            )
        discovery_ratio = max(0.0, min(float(discovery_ratio), 1.0))
        exploration_ratio = max(0.0, min(float(exploration_ratio or 0.0), 0.20))

        # ── Resolve session intent (influences retrieval, ranking, flow) ──
        _intent = None
        _resolution = None
        if _INTENTS_AVAILABLE:
            _resolution = _resolve_intent_with_confidence(
                session_type=session_type, mood=mood,
            )
            if _resolution is not None:
                _intent = _resolution.profile
                # Override exploration ratio from intent profile
                if exploration_ratio <= 0:
                    exploration_ratio = _intent.exploration_ratio
                # Override session_type for flow engine
                session_type = _intent.name
                print(
                    f"[playlist.intent] resolved={_resolution.primary_name} "
                    f"method={_resolution.method} "
                    f"confidence={_resolution.confidence:.2f} "
                    f"exploration={exploration_ratio:.2f} "
                    f"gate={_intent.audio_gate is not None}"
                )
                if _resolution.method == "blend":
                    print(
                        f"[playlist.intent.blend] "
                        f"primary={_resolution.primary_name} "
                        f"secondary={_resolution.secondary_name} "
                        f"ratio={_resolution.blend_ratio:.2f}"
                    )
                if _resolution.pre_soften_tier > 0:
                    print(
                        f"[playlist.intent.soften] "
                        f"pre_soften_tier={_resolution.pre_soften_tier} "
                        f"reason=confidence<committed"
                    )

        # ── Optional runtime trace (no-op when disabled) ──────────────────
        _trace = None
        if _TRACE_AVAILABLE and is_trace_enabled():
            _trace = PipelineTrace()
            _trace.start("pipeline_total")

        _fallback_history = []

        if not user_tracks:
            user_tracks = self._curated_familiar_seed_tracks(region_key, mood)
            if user_tracks:
                _fallback_history.append("curated_familiar_seed_tracks")
                print(f"[playlist.seed] region={region_key} injected={len(user_tracks)}")

        # ── Intent audio gate: adaptive pre-filter BEFORE scoring ─────────
        # Pre-soften gate when confidence is moderate/weak to prevent starvation
        _lib_health = None
        if _intent is not None:
            _gate_intent = _intent
            if _resolution is not None and _resolution.pre_soften_tier > 0:
                _softened_gate = _relax_gate(
                    _intent.audio_gate, _resolution.pre_soften_tier,
                )
                # Build a temporary IntentProfile with the softened gate
                _gate_intent = IntentProfile(
                    name=_intent.name,
                    description=_intent.description,
                    audio_gate=_softened_gate,
                    score_weights=_intent.score_weights,
                    exploration_ratio=_intent.exploration_ratio,
                    novelty_tolerance=_intent.novelty_tolerance,
                    min_semantic_relatedness=_intent.min_semantic_relatedness,
                    mood_consistency=_intent.mood_consistency,
                    artist_repeat_limit=_intent.artist_repeat_limit,
                    flow_profile=_intent.flow_profile,
                    lyrical_density=_intent.lyrical_density,
                    emotional_variance=_intent.emotional_variance,
                    mood_keywords=_intent.mood_keywords,
                    anti_keywords=_intent.anti_keywords,
                    phases=_intent.phases,
                )
            user_tracks, _lib_health = _adaptive_gate_filter(
                user_tracks, _gate_intent,
                min_pool_size=max(15, playlist_size),
                min_artist_diversity=5,
                pool_name="library",
            )
            _validate_pipeline_stage(
                PipelineStage.POST_INTENT_GATE,
                pool_health=_lib_health,
                target_size=max(15, playlist_size),
            )
            _validate_pipeline_stage(
                PipelineStage.ADAPTIVE_RELAXATION,
                pool_health=_lib_health,
                fallback_history=_fallback_history,
            )
            if _lib_health.relaxation_tier > 0:
                exploration_ratio = _relaxed_exploration_ratio(_intent, _lib_health)
                print(
                    f"[playlist.intent.gate] pool=library "
                    f"tier={_lib_health.relaxation_tier} "
                    f"survival={_lib_health.survival_rate:.1%} "
                    f"exploration_adj={exploration_ratio:.2f}"
                )
            elif _lib_health.pre_gate_count != _lib_health.post_gate_count:
                print(
                    f"[playlist.intent.gate] pool=library "
                    f"removed={_lib_health.pre_gate_count - _lib_health.post_gate_count} "
                    f"remaining={_lib_health.post_gate_count}"
                )

        _validate_pipeline_stage(
            PipelineStage.CANDIDATE_RETRIEVAL,
            tracks=user_tracks,
            min_count=min(max(1, playlist_size), max(15, playlist_size)),
        )
        print(f"[playlist.library] scoring={len(user_tracks)}")
        if _trace:
            _trace.start("genome_scoring")
        library_scored = self._score_tracks_by_genome(
            user_tracks, genome, mood, region_key, taste_profile, user_embedding,
            intent=_intent,
        )
        if _trace:
            _trace.stop("genome_scoring", metadata={"pool": "library", "count": len(library_scored)})
        if mood:
            library_scored = self._mood_filter_with_fallback(library_scored, mood, "library", region_key, genome)

        discovered_tracks = []
        discovery_limit = max(50, playlist_size * 4)
        print(f"[playlist.discovery] region={region_key} cluster={cluster_id} limit={discovery_limit}")

        if _trace:
            _trace.start("candidate_retrieval")
        if self.spotify_service:
            try:
                discovered_tracks = self.spotify_service.search_regional_tracks(
                    cluster_id=cluster_id,
                    region_key=region_key,
                    limit=discovery_limit,
                )
                print(f"[playlist.discovery] found={len(discovered_tracks)}")
                if _trace:
                    _trace.add_cache_event("regional", hit=bool(getattr(self.spotify_service, 'regional_cache', {}).get(("regional", region_key, cluster_id, discovery_limit))))
                for i, track in enumerate(discovered_tracks[:3], 1):
                    print(f"[playlist.discovery.sample] {i}. {track.get('name')} - {track.get('artist')}")
            except Exception as e:
                print(f"[playlist.discovery.error] error={e}")
                if _trace:
                    _trace.add_warning("candidate_retrieval", type(e).__name__, str(e))
        else:
            print("[playlist.discovery] spotify_service=false")
        if _trace:
            _trace.stop("candidate_retrieval", metadata={"discovered": len(discovered_tracks)})

        _validate_pipeline_stage(
            PipelineStage.CANDIDATE_RETRIEVAL,
            tracks=discovered_tracks,
            min_count=min(max(1, playlist_size), discovery_limit),
        )

        discovered_scored = []
        if discovered_tracks:
            print("[playlist.features] enriching=true")
            discovered_tracks = self._apply_novelty_labels(discovered_tracks, user_tracks)
            discovered_tracks = self._fetch_audio_features_batch(discovered_tracks)
            # Intent audio gate on discovery pool (adaptive)
            # Apply same pre-softening as library pool
            if _intent is not None:
                _disc_gate_intent = _intent
                if _resolution is not None and _resolution.pre_soften_tier > 0:
                    _softened_disc_gate = _relax_gate(
                        _intent.audio_gate, _resolution.pre_soften_tier,
                    )
                    _disc_gate_intent = IntentProfile(
                        name=_intent.name,
                        description=_intent.description,
                        audio_gate=_softened_disc_gate,
                        score_weights=_intent.score_weights,
                        exploration_ratio=_intent.exploration_ratio,
                        novelty_tolerance=_intent.novelty_tolerance,
                        min_semantic_relatedness=_intent.min_semantic_relatedness,
                        mood_consistency=_intent.mood_consistency,
                        artist_repeat_limit=_intent.artist_repeat_limit,
                        flow_profile=_intent.flow_profile,
                        lyrical_density=_intent.lyrical_density,
                        emotional_variance=_intent.emotional_variance,
                        mood_keywords=_intent.mood_keywords,
                        anti_keywords=_intent.anti_keywords,
                        phases=_intent.phases,
                    )
                discovered_tracks, _disc_health = _adaptive_gate_filter(
                    discovered_tracks, _disc_gate_intent,
                    min_pool_size=max(15, playlist_size),
                    min_artist_diversity=5,
                    pool_name="discovery",
                )
                _validate_pipeline_stage(
                    PipelineStage.POST_INTENT_GATE,
                    pool_health=_disc_health,
                    target_size=max(15, playlist_size),
                )
                _validate_pipeline_stage(
                    PipelineStage.ADAPTIVE_RELAXATION,
                    pool_health=_disc_health,
                    fallback_history=_fallback_history,
                )
                if _disc_health.relaxation_tier > 0:
                    # Use worst health between library and discovery for exploration
                    _worst_health = _disc_health
                    if _lib_health and _lib_health.relaxation_tier > _disc_health.relaxation_tier:
                        _worst_health = _lib_health
                    exploration_ratio = _relaxed_exploration_ratio(_intent, _worst_health)
                    print(
                        f"[playlist.intent.gate] pool=discovery "
                        f"tier={_disc_health.relaxation_tier} "
                        f"survival={_disc_health.survival_rate:.1%} "
                        f"exploration_adj={exploration_ratio:.2f}"
                    )
            discovered_scored = self._score_tracks_by_genome(
                discovered_tracks, genome, mood, region_key, taste_profile, user_embedding,
                intent=_intent,
            )
            if mood:
                discovered_scored = self._mood_filter_with_fallback(discovered_scored, mood, "discovery", region_key, genome)
        else:
            fallback_reason = "spotify_empty_or_failed"
            _fallback_history.append(fallback_reason)
            discovered_tracks = self._internal_discovery_tracks(region_key, mood)
            if discovered_tracks:
                print(f"[playlist.discovery.fallback] reason={fallback_reason} injected={len(discovered_tracks)}")
                _validate_pipeline_stage(
                    PipelineStage.CANDIDATE_RETRIEVAL,
                    tracks=discovered_tracks,
                    min_count=min(max(1, playlist_size), len(discovered_tracks)),
                )
                discovered_tracks = self._apply_novelty_labels(discovered_tracks, user_tracks)
                discovered_scored = self._score_tracks_by_genome(
                    discovered_tracks, genome, mood, region_key, taste_profile, user_embedding
                )
                if mood:
                    discovered_scored = self._mood_filter_with_fallback(discovered_scored, mood, "discovery", region_key, genome)

        num_discovery = int(round(playlist_size * discovery_ratio))
        num_library = playlist_size - num_discovery
        print(f"[playlist.build] familiar_target={num_library} discovery_target={num_discovery}")

        relabeled_library = [st for st in discovered_scored if st["track"].get("source") == "library"]
        real_discovery_scored = self._suppress_duplicate_discovery_artists(
            [st for st in discovered_scored if st["track"].get("source") == "discovery"]
        )
        library_scored = self._dedupe_scored_tracks(library_scored + relabeled_library)
        library_scored = self._apply_recent_memory_penalty(library_scored, region_key)
        real_discovery_scored = self._apply_recent_memory_penalty(real_discovery_scored, region_key)
        library_scored.sort(key=lambda x: x["score"], reverse=True)

        library_selected = library_scored[:num_library]
        discovery_selected = real_discovery_scored[:num_discovery]
        self._fill_shortage(library_selected, discovery_selected, library_scored, real_discovery_scored, playlist_size)

        all_selected = self._dedupe_scored_tracks(library_selected + discovery_selected)
        self._fill_shortage_from_pool(all_selected, library_scored + real_discovery_scored, playlist_size)

        all_selected = self._apply_recent_memory_penalty(all_selected, region_key)
        all_selected = self._apply_request_seeded_diversity(
            all_selected,
            region_key=region_key,
            cluster_id=cluster_id,
        )
        self._attach_final_trace(all_selected)
        exploration_pool = self._exploration_candidate_pool(library_scored + real_discovery_scored)
        playlist_tracks = [item["track"] for item in all_selected[:playlist_size]]
        if mood:
            playlist_tracks = self._enforce_final_mood(playlist_tracks, mood, region_key, genome, playlist_size)

        if _trace:
            _trace.start("exploration_injection")
        pre_exploration = list(playlist_tracks)
        playlist_tracks = self._inject_controlled_exploration(
            playlist_tracks=playlist_tracks,
            candidate_pool=exploration_pool,
            user_embedding=user_embedding,
            exploration_ratio=exploration_ratio,
        )
        _validate_pipeline_stage(
            PipelineStage.EXPLORATION_INJECTION,
            before_tracks=pre_exploration,
            after_tracks=playlist_tracks,
            candidate_pool=exploration_pool,
            requested_ratio=exploration_ratio,
        )
        if _trace:
            _trace.stop("exploration_injection", metadata={"injected": sum(1 for t in playlist_tracks if t.get("exploration"))})
            trace_exploration(_trace, pre_exploration, playlist_tracks)

        if target_minutes:
            playlist_tracks, duration_diagnostics = self._select_tracks_by_duration_budget(
                playlist_tracks,
                target_minutes,
                tolerance=DURATION_TOLERANCE,
            )
            print(
                "[playlist.duration] "
                f"target={target_minutes}m actual={duration_diagnostics['actual_minutes']}m "
                f"tracks={duration_diagnostics['selected_count']} "
                f"met={duration_diagnostics['target_met']}"
            )

        # ── Flow sequencing (optional, post-ranking, pre-serialization) ────────
        if _reorder_for_flow is not None and playlist_tracks:
            _validate_pipeline_stage(
                PipelineStage.SEQUENCING_PRECONDITION,
                tracks=playlist_tracks,
            )
            if _trace:
                _trace.start("flow_sequencing")
            pre_flow = list(playlist_tracks)
            playlist_tracks = _reorder_for_flow(
                playlist_tracks,
                session_type=session_type,
                protect_top=1,
            )
            if _trace:
                _trace.stop("flow_sequencing", metadata={"session_type": session_type or "default"})
                trace_flow_reorder(_trace, pre_flow, playlist_tracks)

        _validate_pipeline_stage(
            PipelineStage.FINAL_ORDERED_PLAYLIST,
            tracks=playlist_tracks,
            requested_size=len(playlist_tracks) if target_minutes else requested_track_count,
            requested_exploration_ratio=exploration_ratio,
        )

        self._remember_served_tracks(region_key, playlist_tracks)
        characteristics = self._analyze_playlist(playlist_tracks)
        characteristics["discovery_count"] = sum(1 for t in playlist_tracks if t.get("source") == "discovery")
        characteristics["library_count"] = len(playlist_tracks) - characteristics["discovery_count"]
        characteristics["familiar_count"] = characteristics["library_count"]
        characteristics["exploration_count"] = sum(1 for t in playlist_tracks if t.get("exploration"))
        self._log_debug_evaluation(playlist_tracks, user_embedding)

        print(f"\n[playlist.final] returned={len(playlist_tracks)} requested={playlist_size}")
        print(
            f"[playlist.final.truth] familiar_count={characteristics['library_count']} "
            f"discovery_count={characteristics['discovery_count']}"
        )
        for i, track in enumerate(playlist_tracks[:5], 1):
            print(f"   {i}. {track.get('source')} {track.get('name')} - {track.get('artist')}")
        if len(playlist_tracks) > 5:
            print(f"   ... and {len(playlist_tracks) - 5} more tracks")
        print()

        result = {
            "name": self._generate_regional_playlist_name(region_key, cluster_id, mood),
            "tracks": playlist_tracks,
            "size": len(playlist_tracks),
            "type": "regional_genome",
            "region": region_key,
            "cluster_id": cluster_id,
            "discovery_ratio": discovery_ratio,
            "exploration_ratio": exploration_ratio,
            "mood": mood,
            "target_minutes": target_minutes,
            "actual_minutes": round(characteristics.get("total_duration_ms", 0) / 60000, 1),
            "duration_target_met": duration_diagnostics.get("target_met") if duration_diagnostics else None,
            "duration_diagnostics": duration_diagnostics,
            "characteristics": characteristics,
            "familiar_count": characteristics["library_count"],
            "discovery_count": characteristics["discovery_count"],
            "exploration_count": characteristics["exploration_count"],
            "description": self._generate_regional_description(region_key, characteristics, mood),
        }
        if include_explanations and generate_playlist_explanations is not None:
            result["recommendation_explanations"] = generate_playlist_explanations(
                playlist_tracks,
                taste_profile=taste_profile,
                requested_mood=mood,
            )
            print(f"[playlist.explanations] generated={len(result['recommendation_explanations'])}")
        # Attach flow report in debug/dev environments (NO-OP in production)
        if _evaluate_flow is not None and is_flow_debug_enabled():
            try:
                result["flow_report"] = _evaluate_flow(
                    playlist_tracks, session_type=session_type
                )
            except Exception:
                pass
        if _trace:
            _trace.stop("pipeline_total", metadata={"tracks": len(playlist_tracks), "region": region_key})
            log_trace_if_enabled(_trace)
        # ── Monitoring: record metrics from this request ─────────────────────
        if _MONITORING_AVAILABLE and is_monitoring_enabled():
            try:
                _ms = _get_metrics_store()
                _ms.record_counter("playlist_generated")
                _ms.record_session_type(session_type or "default")
                _ms.record_ratio("candidate_nonempty", len(discovered_tracks) > 0)
                _ms.record_ratio("exploration_injection", characteristics.get("exploration_count", 0) > 0)
                _ms.record_ratio("playlist_success", True)
                # Diversity: unique artists / total tracks
                if playlist_tracks:
                    _artists = {self._primary_artist(t) for t in playlist_tracks if self._primary_artist(t)}
                    _ms.record_quality("playlist_diversity", len(_artists) / len(playlist_tracks))
                # Latency from trace if available
                if _trace:
                    for _stage in ["pipeline_total", "candidate_retrieval", "genome_scoring",
                                   "exploration_injection", "flow_sequencing"]:
                        _dur = _trace.get_duration_ms(_stage)
                        if _dur is not None:
                            _lat_name = "recommendation_total" if _stage == "pipeline_total" else _stage
                            _ms.record_latency(_lat_name, _dur)
            except Exception:
                pass
        return result

    def generate_pure_discovery_playlist(
        self,
        genome: dict,
        cluster_id: int,
        region_key: str,
        playlist_size: int = 30,
        mood: Optional[str] = None,
    ) -> dict:
        if not self.spotify_service:
            raise Exception("Spotify service required for discovery")

        discovered_tracks = self.spotify_service.search_regional_tracks(
            cluster_id=cluster_id,
            region_key=region_key,
            limit=max(50, playlist_size * 4),
        )
        discovered_tracks = self._fetch_audio_features_batch(discovered_tracks)
        discovered_scored = self._score_tracks_by_genome(discovered_tracks, genome, mood, region_key)
        if mood:
            discovered_scored = self._mood_filter_with_fallback(discovered_scored, mood, "discovery", region_key, genome)

        playlist_tracks = [item["track"] for item in discovered_scored[:playlist_size]]
        characteristics = self._analyze_playlist(playlist_tracks)
        return {
            "name": f"Pure {region_key.replace('_', ' ').title()} Discovery",
            "tracks": playlist_tracks,
            "size": len(playlist_tracks),
            "type": "pure_discovery",
            "region": region_key,
            "cluster_id": cluster_id,
            "characteristics": characteristics,
            "description": f"Fresh {region_key.replace('_', ' ')} tracks matched to your genome.",
        }

    def _exploration_candidate_pool(self, scored_tracks: List[dict]) -> List[dict]:
        pool = []
        seen = set()
        for item in sorted(scored_tracks, key=lambda x: x["score"], reverse=True):
            track = dict(item["track"])
            key = self._track_key(track)
            if key in seen:
                continue
            seen.add(key)
            track["primary_score"] = item["score"]
            pool.append(track)
        return pool

    def _attach_final_trace(self, scored_tracks: List[dict]) -> None:
        for index, item in enumerate(scored_tracks, 1):
            track = item.get("track", {})
            trace = track.setdefault("recommendation_trace", {})
            trace["final_rank_score"] = round(item.get("score", 0.0), 3)
            trace["pre_exploration_rank"] = index
            if item.get("graph_flow_bonus") is not None:
                trace["graph_flow_bonus"] = round(item.get("graph_flow_bonus", 0.0), 4)

    def _inject_controlled_exploration(
        self,
        playlist_tracks: List[dict],
        candidate_pool: List[dict],
        user_embedding=None,
        exploration_ratio: float = 0.0,
    ) -> List[dict]:
        if (
            exploration_ratio <= 0
            or user_embedding is None
            or inject_exploration_tracks is None
            or not playlist_tracks
            or not candidate_pool
        ):
            return playlist_tracks

        ranker = getattr(getattr(self, "spotify_service", None), "embedding_ranker", None)
        if not ranker:
            return playlist_tracks

        selected_ids = {self._track_key(track) for track in playlist_tracks}
        candidates = [track for track in candidate_pool if self._track_key(track) not in selected_ids]
        if not candidates:
            return playlist_tracks

        try:
            graph_tracks = playlist_tracks + candidates
            graph_texts = [ranker.build_text(track) for track in graph_tracks]
            graph_embeddings = ranker.embed_texts_cached(graph_texts)
            candidate_embeddings = graph_embeddings[len(playlist_tracks):]
            track_graph = None
            if TrackGraph is not None and len(graph_tracks) == len(graph_embeddings):
                track_graph = TrackGraph(top_k=10).build(graph_tracks, graph_embeddings)
            return inject_exploration_tracks(
                playlist_tracks=playlist_tracks,
                candidate_pool=candidates,
                playlist_size=len(playlist_tracks),
                user_embedding=user_embedding,
                candidate_embeddings=candidate_embeddings,
                track_graph=track_graph,
                exploration_ratio=exploration_ratio,
            )
        except Exception as exc:
            print(f"[playlist.exploration.error] error={exc}")
            return playlist_tracks

    def _score_tracks_by_genome(
        self,
        tracks: List[dict],
        genome: dict,
        mood: Optional[str] = None,
        region_key: Optional[str] = None,
        taste_profile: Optional[dict] = None,
        user_embedding=None,
        intent=None,
    ) -> List[dict]:
        # Resolve scoring weights: intent > config > defaults
        if intent is not None and _INTENTS_AVAILABLE:
            _w = intent.score_weights
            w_genome = _w.genome_weight
            w_pop = _w.popularity_weight
            w_mood = _w.mood_weight
            w_region = _w.region_weight
            w_quality = _w.quality_weight
        elif _SCORING_CFG_AVAILABLE:
            w_genome = _RCFG.GENOME_WEIGHT
            w_pop = _RCFG.POPULARITY_WEIGHT
            w_mood = _RCFG.MOOD_WEIGHT
            w_region = _RCFG.REGION_WEIGHT
            w_quality = _RCFG.QUALITY_WEIGHT
        else:
            w_genome, w_pop, w_mood, w_region, w_quality = 0.38, 0.25, 0.17, 0.12, 0.08

        # Intent keyword bonus function
        _intent_kw_bonus = 0.0
        _intent_kw_penalty = 0.0
        if intent is not None and _INTENTS_AVAILABLE:
            _kw_set = set(intent.mood_keywords)
            _anti_set = set(intent.anti_keywords)
        else:
            _kw_set = set()
            _anti_set = set()

        scored = []
        for track in tracks:
            self._ensure_audio_features(track)
            genome_score = self._calculate_genome_match_score(track, genome)
            popularity_score = track.get("popularity", 0) / 100
            mood_score = self._lexical_mood_score(track, mood)
            region_score = track.get("region_confidence", 0.65 if region_key else 0.5)
            quality_score = track.get("quality_score", 0.5)

            score = (
                genome_score * w_genome
                + popularity_score * w_pop
                + mood_score * w_mood
                + region_score * w_region
                + quality_score * w_quality
            )

            # Intent keyword affinity: boost tracks matching intent vocabulary
            if _kw_set or _anti_set:
                text = f"{track.get('name', '')} {track.get('artist', '')} {track.get('search_query', '')}".lower()
                kw_hits = sum(1 for kw in _kw_set if kw in text)
                anti_hits = sum(1 for kw in _anti_set if kw in text)
                score += kw_hits * 0.03 - anti_hits * 0.04

            track["recommendation_trace"] = {
                "genome_score": round(genome_score, 3),
                "popularity_score": round(popularity_score, 3),
                "mood_score": round(mood_score, 3),
                "region_score": round(region_score, 3),
                "quality_score": round(quality_score, 3),
                "primary_score": round(score, 3),
            }
            if intent is not None:
                track["recommendation_trace"]["intent"] = intent.name
            scored.append({"track": track, "score": score})

        scored.sort(key=lambda x: x["score"], reverse=True)
        if user_embedding is not None:
            scored = self._apply_user_embedding_similarity(scored, user_embedding)
        # Optional: lightweight graph-flow reranking (additive only, does not
        # override primary genome/embedding signal).
        track_graph = getattr(self, "track_graph", None)
        if track_graph is not None:
            scored = self._apply_graph_flow_reranking(scored, track_graph)
        return scored

    def _apply_user_embedding_similarity(self, scored_tracks: List[dict], user_embedding) -> List[dict]:
        ranker = getattr(getattr(self, "spotify_service", None), "embedding_ranker", None)
        if not ranker or user_embedding is None or len(scored_tracks) < 2:
            return scored_tracks
        try:
            texts = []
            for item in scored_tracks:
                track = item["track"]
                texts.append(ranker.build_text(track))
            track_embeddings = ranker.embed_texts_cached(texts)
            reranked = []
            for item, track_embedding in zip(scored_tracks, track_embeddings):
                semantic_score = (cosine_similarity(user_embedding, track_embedding) + 1.0) / 2.0
                item["track"]["user_embedding_similarity"] = round(semantic_score, 3)
                trace = item["track"].setdefault("recommendation_trace", {})
                trace["semantic_similarity"] = round(semantic_score, 3)
                trace["pre_embedding_score"] = round(item["score"], 3)
                reranked.append({
                    "track": item["track"],
                    "score": (
                        item["score"] * (_RCFG.PRE_EMBED_RETAIN if _SCORING_CFG_AVAILABLE else 0.78)
                        + semantic_score * (_RCFG.EMBED_WEIGHT if _SCORING_CFG_AVAILABLE else 0.22)
                    ),
                })
                item["track"]["recommendation_trace"]["post_embedding_score"] = round(reranked[-1]["score"], 3)
            reranked.sort(key=lambda x: x["score"], reverse=True)
            return reranked
        except Exception as e:
            print(f"[playlist.user_embedding.error] error={e}")
        return scored_tracks

    def _apply_graph_flow_reranking(
        self,
        scored_tracks: List[dict],
        track_graph: "TrackGraph",  # type: ignore[name-defined]
    ) -> List[dict]:
        """
        Optional, additive graph-flow pass.

        Softly rewards playlist-flow continuity using the semantic
        neighborhood graph built by track_graph.py.  The primary genome
        and embedding scores are preserved; this only adds a tiny bonus
        (≤ 0.08) to tracks that neighbour the preceding track, improving
        transition quality without altering overall ranking substantially.
        """
        if track_graph is None or len(scored_tracks) < 2:
            return scored_tracks
        try:
            reranked = track_graph.rerank_for_flow(scored_tracks)
            for item in reranked:
                bonus = item.get("graph_flow_bonus", 0.0)
                trace = item["track"].setdefault("recommendation_trace", {})
                trace["graph_flow_bonus"] = round(bonus, 4)
                trace["post_graph_score"] = round(item.get("score", 0.0), 3)
                item["track"]["graph_flow_bonus"] = round(bonus, 4)
            return reranked
        except Exception as exc:
            print(f"[playlist.graph_flow.error] error={exc}")
            return scored_tracks

    def _log_debug_evaluation(self, tracks: List[dict], user_embedding=None) -> None:
        mode = (os.getenv("SONICDNA_ENV") or os.getenv("APP_ENV") or os.getenv("ENV") or "").lower()
        debug_enabled = os.getenv("DEBUG_EVALUATION", "").lower() in {"1", "true", "yes"}
        if mode not in {"development", "dev", "local", "debug"} and not debug_enabled:
            return

        ranker = getattr(getattr(self, "spotify_service", None), "embedding_ranker", None)

        def track_embedding(track: dict):
            if not ranker:
                return None
            return ranker.embed_cached(ranker.build_text(track))

        try:
            metrics = evaluate_playlist(
                tracks,
                user_embedding=user_embedding,
                track_embedding_fn=track_embedding if ranker else None,
            )
            diversity = metrics["diversity"]
            novelty = metrics["novelty"]
            semantic = metrics["semantic"]
            semantic_match = semantic["semantic_match"] if semantic["semantic_match"] is not None else "n/a"
            print(
                "[evaluation] "
                f"diversity=artists:{diversity['unique_artists_ratio']} genres:{diversity['unique_genres_ratio']} "
                f"novelty=inverse_popularity:{novelty['inverse_popularity']} balance:{novelty['mainstream_niche_balance']} "
                f"semantic_match={semantic_match} "
                "overlap=n/a"
            )
        except Exception as e:
            print(f"[evaluation.error] error={e}")

        if _evaluate_flow is not None and is_flow_debug_enabled():
            try:
                session_type = getattr(self, "_last_session_type", None)
                flow_report = _evaluate_flow(tracks, session_type=session_type)
                fq = flow_report.get("flow_quality", {})
                ap = flow_report.get("anti_pattern_count", 0)
                print(
                    f"[flow_eval] score={fq.get('overall_flow_score','?')} "
                    f"grade={fq.get('grade','?')} "
                    f"entropy={fq.get('flow_entropy','?')} "
                    f"adherence={flow_report.get('session_adherence',{}).get('adherence_score','?')} "
                    f"anti_patterns={ap}"
                )
                if ap:
                    for p in flow_report.get("anti_patterns", []):
                        print(f"  [anti_pattern] {p['severity']} | {p['pattern']}: {p['detail']}")
            except Exception as _fe:
                print(f"[flow_eval.error] {_fe}")

    def _fetch_audio_features_batch(self, tracks: List[dict]) -> List[dict]:
        tracks_needing_features = [t for t in tracks if "danceability" not in t]
        if not tracks_needing_features:
            return tracks

        for track in tracks_needing_features:
            fallback = self._heuristic_audio_features(track)
            track.update(fallback)
            track["feature_source"] = "heuristic"
            track.setdefault("source", "discovery")

        return tracks

    def _heuristic_audio_features(self, track: dict) -> dict:
        text = self._track_text(track)
        popularity = max(0, min(track.get("popularity", 45), 100)) / 100
        duration_ms = track.get("duration_ms") or 180_000
        duration_energy = 0.08 if 130_000 <= duration_ms <= 260_000 else -0.03

        dance_terms = ["dance", "party", "bhangra", "pop", "hit", "club", "kuthu", "beat"]
        calm_terms = ["chill", "lofi", "soft", "acoustic", "sleep", "study", "smooth"]
        sad_terms = ["sad", "heart", "alone", "lonely", "slow", "rain"]
        speech_terms = ["rap", "hip hop", "spoken"]

        dance_boost = 0.16 if any(term in text for term in dance_terms) else 0
        calm_boost = 0.14 if any(term in text for term in calm_terms) else 0
        sad_boost = 0.12 if any(term in text for term in sad_terms) else 0
        speech_boost = 0.12 if any(term in text for term in speech_terms) else 0

        seed = int(hashlib.sha1(str(track.get("id") or text).encode()).hexdigest()[:8], 16)
        jitter = ((seed % 100) / 1000) - 0.05

        danceability = self._clamp(0.48 + popularity * 0.20 + dance_boost - calm_boost * 0.3 + jitter)
        energy = self._clamp(0.46 + popularity * 0.22 + dance_boost + duration_energy - calm_boost + jitter)
        valence = self._clamp(0.48 + popularity * 0.12 + dance_boost * 0.4 - sad_boost + jitter)
        acousticness = self._clamp(0.35 + calm_boost - dance_boost * 0.5 - popularity * 0.08)
        instrumentalness = self._clamp(0.03 + (0.08 if "score" in text else 0))
        speechiness = self._clamp(0.05 + speech_boost)

        return {
            "danceability": danceability,
            "energy": energy,
            "valence": valence,
            "acousticness": acousticness,
            "instrumentalness": instrumentalness,
            "speechiness": speechiness,
            "tempo": 95 + int(70 * energy),
            "duration_ms": duration_ms,
        }

    def _ensure_audio_features(self, track: dict) -> dict:
        if any(track.get(feature) is None for feature in FALLBACK_AUDIO_FEATURES):
            track.update(self._heuristic_audio_features(track))
            track.setdefault("feature_source", "heuristic")
        if track.get("tempo") is None:
            track["tempo"] = 120.0
        if track.get("duration_ms") is None:
            track["duration_ms"] = 180_000
        return track

    def _calculate_genome_match_score(self, track: dict, target_genome: dict) -> float:
        track_genome = {
            "danceability": (track.get("danceability", 0.5) - 0.5) * 4,
            "energy": (track.get("energy", 0.5) - 0.5) * 4,
            "valence": (track.get("valence", 0.5) - 0.5) * 4,
            "acousticness": (track.get("acousticness", 0.5) - 0.5) * 4,
            "instrumentalness": (track.get("instrumentalness", 0.0) - 0.5) * 4,
            "speechiness": (track.get("speechiness", 0.05) - 0.5) * 4,
        }
        features = ["danceability", "energy", "valence", "acousticness", "instrumentalness", "speechiness"]
        distance = sum((track_genome.get(f, 0) - target_genome.get(f, 0)) ** 2 for f in features) ** 0.5
        max_distance = (4 ** 2 * 6) ** 0.5
        return self._clamp(1 - (distance / max_distance))

    def _filter_by_mood(self, scored_tracks: List[dict], mood: str) -> List[dict]:
        mood_key = mood.lower().strip() if mood else ""
        mood_filters = {
            "happy": lambda t: t["track"].get("valence", 0.5) > 0.58 or self._lexical_mood_score(t["track"], mood) > 0.35,
            "sad": lambda t: t["track"].get("valence", 0.5) < 0.46 or self._lexical_mood_score(t["track"], mood) > 0.35,
            "energetic": lambda t: t["track"].get("energy", 0.5) > 0.58 or self._lexical_mood_score(t["track"], mood) > 0.35,
            "calm": lambda t: self._is_mood_compliant(t["track"], "calm"),
            "focused": lambda t: (
                t["track"].get("instrumentalness", 0) > 0.25
                or t["track"].get("energy", 0.5) < 0.62
                or self._lexical_mood_score(t["track"], mood) > 0.35
            ),
        }
        filter_fn = mood_filters.get(mood_key)
        return [st for st in scored_tracks if filter_fn(st)] if filter_fn else scored_tracks

    def _mood_filter_with_fallback(
        self,
        scored_tracks: List[dict],
        mood: str,
        pool_name: str,
        region_key: str,
        genome: dict,
    ) -> List[dict]:
        filtered = self._filter_by_mood(scored_tracks, mood)
        if not filtered and scored_tracks:
            fallback_tracks = self._mood_safe_internal_tracks(region_key, mood, source=pool_name)
            fallback_scored = self._score_tracks_by_genome(fallback_tracks, genome, mood, region_key)
            fallback_filtered = self._filter_by_mood(fallback_scored, mood)
            if not fallback_filtered:
                print(
                    f"[playlist.mood] pool={pool_name} fallback=true mood={mood} "
                    "injected=0 retain_original=true"
                )
                return scored_tracks
            print(
                f"[playlist.mood] pool={pool_name} fallback=true mood={mood} "
                f"injected={len(fallback_filtered)}"
            )
            return fallback_filtered
        return filtered

    def _is_mood_compliant(self, track: dict, mood: str) -> bool:
        mood_key = mood.lower().strip() if mood else ""
        if mood_key != "calm":
            return True

        text = self._track_text(track)
        if any(term in text for term in PARTY_REJECT_TERMS):
            return False

        energy = track.get("energy", 0.5)
        valence = track.get("valence", 0.5)
        tempo = track.get("tempo", 120)
        return energy <= 0.55 and 0.25 <= valence <= 0.72 and tempo <= 132

    def _enforce_final_mood(
        self,
        tracks: List[dict],
        mood: str,
        region_key: str,
        genome: dict,
        playlist_size: int,
    ) -> List[dict]:
        if mood.lower().strip() != "calm":
            return tracks

        compliant = [track for track in tracks if self._is_mood_compliant(track, mood)]
        if len(compliant) == len(tracks):
            return tracks

        fallback = self._mood_safe_internal_tracks(region_key, mood, source="library")
        fallback += self._mood_safe_internal_tracks(region_key, mood, source="discovery")
        fallback_scored = self._score_tracks_by_genome(fallback, genome, mood, region_key)
        for item in fallback_scored:
            track = item["track"]
            if len(compliant) >= playlist_size:
                break
            if self._is_mood_compliant(track, mood) and self._track_key(track) not in {self._track_key(t) for t in compliant}:
                compliant.append(track)

        print(
            f"[playlist.mood.final] mood={mood} removed={len(tracks) - len(compliant)} "
            f"returned={len(compliant)}"
        )
        return compliant[:playlist_size]

    def _lexical_mood_score(self, track: dict, mood: Optional[str]) -> float:
        if not mood:
            return 0.5
        text = self._track_text(track)
        terms = MOOD_TERMS.get(mood.lower().strip(), [])
        if not terms:
            return 0.5
        hits = sum(1 for term in terms if term in text)
        _base = _RCFG.MOOD_BASE          if _SCORING_CFG_AVAILABLE else 0.35
        _incr = _RCFG.MOOD_HIT_INCREMENT if _SCORING_CFG_AVAILABLE else 0.22
        return min(1.0, _base + hits * _incr)

    def _fill_shortage(
        self,
        library_selected: List[dict],
        discovery_selected: List[dict],
        library_scored: List[dict],
        discovered_scored: List[dict],
        playlist_size: int,
    ) -> None:
        while len(library_selected) + len(discovery_selected) < playlist_size:
            before = len(library_selected) + len(discovery_selected)
            self._append_next_unique(discovery_selected, discovered_scored, library_selected + discovery_selected)
            if len(library_selected) + len(discovery_selected) >= playlist_size:
                break
            self._append_next_unique(library_selected, library_scored, library_selected + discovery_selected)
            if len(library_selected) + len(discovery_selected) == before:
                break

    def _fill_shortage_from_pool(self, selected: List[dict], pool: List[dict], playlist_size: int) -> None:
        while len(selected) < playlist_size:
            before = len(selected)
            self._append_next_unique(selected, pool, selected)
            if len(selected) == before:
                break

    def _append_next_unique(self, target: List[dict], source: List[dict], existing: List[dict]) -> None:
        existing_ids = {self._track_key(item["track"]) for item in existing}
        for item in source:
            key = self._track_key(item["track"])
            if key not in existing_ids:
                target.append(item)
                return

    def _dedupe_scored_tracks(self, scored_tracks: List[dict]) -> List[dict]:
        deduped = []
        seen = set()
        for item in scored_tracks:
            key = self._track_key(item["track"])
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        return deduped

    def _duration_candidate_track_budget(self, target_minutes: int) -> int:
        target_ms = max(1, int(target_minutes)) * 60_000
        estimated_short_track_ms = 150_000
        return max(8, min(50, int(target_ms / estimated_short_track_ms) + 8))

    def _track_duration_ms(self, track: dict) -> int:
        try:
            duration = int(track.get("duration_ms") or FALLBACK_DURATION_MS)
        except (TypeError, ValueError):
            duration = FALLBACK_DURATION_MS
        return max(MIN_DURATION_TRACK_MS, duration)

    def _select_tracks_by_duration_budget(
        self,
        tracks: List[dict],
        target_minutes: int,
        tolerance: float = DURATION_TOLERANCE,
    ) -> tuple[List[dict], dict]:
        if not tracks:
            return [], {
                "target_minutes": target_minutes,
                "actual_minutes": 0.0,
                "target_met": False,
                "selected_count": 0,
                "considered_count": 0,
                "tolerance_pct": tolerance,
                "method": "duration_budget_dp",
            }

        target_ms = max(1, int(target_minutes)) * 60_000
        lower_ms = int(target_ms * (1.0 - tolerance))
        upper_ms = int(target_ms * (1.0 + tolerance))
        target_sec = round(target_ms / 1000)
        lower_sec = round(lower_ms / 1000)
        upper_sec = max(1, round(upper_ms / 1000))

        durations_sec = [max(1, round(self._track_duration_ms(track) / 1000)) for track in tracks]
        states: dict[int, tuple[int, ...]] = {0: ()}

        def better(candidate: tuple[int, ...], current: Optional[tuple[int, ...]]) -> bool:
            if current is None:
                return True
            candidate_rank = sum(candidate)
            current_rank = sum(current)
            if len(candidate) != len(current):
                return len(candidate) > len(current)
            return candidate_rank < current_rank

        for index, duration_sec in enumerate(durations_sec):
            snapshot = list(states.items())
            for total_sec, indices in snapshot:
                next_total = total_sec + duration_sec
                if next_total > upper_sec:
                    continue
                candidate = indices + (index,)
                if better(candidate, states.get(next_total)):
                    states[next_total] = candidate

        feasible_totals = [total for total in states if lower_sec <= total <= upper_sec and states[total]]
        if feasible_totals:
            best_total = min(feasible_totals, key=lambda total: (abs(total - target_sec), -total, len(states[total])))
            selected_indices = states[best_total]
        else:
            non_empty = [total for total in states if states[total]]
            if non_empty:
                best_total = min(non_empty, key=lambda total: (abs(total - target_sec), -total, len(states[total])))
                selected_indices = states[best_total]
            else:
                selected_indices = (0,)

        selected = [tracks[index] for index in selected_indices]
        total_ms = sum(self._track_duration_ms(track) for track in selected)
        diagnostics = {
            "target_minutes": int(target_minutes),
            "target_ms": target_ms,
            "lower_ms": lower_ms,
            "upper_ms": upper_ms,
            "total_duration_ms": total_ms,
            "actual_minutes": round(total_ms / 60_000, 1),
            "target_met": lower_ms <= total_ms <= upper_ms,
            "selected_count": len(selected),
            "considered_count": len(tracks),
            "tolerance_pct": tolerance,
            "method": "duration_budget_dp",
        }
        return selected, diagnostics

    def _limit_tracks_by_duration(self, tracks: List[dict], target_minutes: int, min_tracks: int = 1) -> List[dict]:
        target_ms = target_minutes * 60_000
        selected = []
        total_ms = 0

        for track in tracks:
            duration = track.get("duration_ms", 180_000)
            if total_ms + duration <= target_ms or len(selected) < min_tracks:
                selected.append(track)
                total_ms += duration

        return selected

    def _analyze_playlist(self, tracks: List[dict]) -> dict:
        if not tracks:
            return {"tags": [], "total_duration_ms": 0}

        characteristics = {}
        for feature in ["danceability", "energy", "valence", "acousticness", "instrumentalness", "speechiness", "tempo"]:
            values = [t.get(feature) for t in tracks if t.get(feature) is not None]
            if values:
                characteristics[feature] = {"avg": sum(values) / len(values), "min": min(values), "max": max(values)}

        tags = []
        avg_dance = characteristics.get("danceability", {}).get("avg", 0.5)
        avg_energy = characteristics.get("energy", {}).get("avg", 0.5)
        avg_valence = characteristics.get("valence", {}).get("avg", 0.5)
        avg_acoustic = characteristics.get("acousticness", {}).get("avg", 0.5)

        if avg_dance > 0.66:
            tags.append("Danceable")
        if avg_energy > 0.66:
            tags.append("High Energy")
        if avg_valence > 0.66:
            tags.append("Positive")
        elif avg_valence < 0.36:
            tags.append("Melancholic")
        if avg_acoustic > 0.58:
            tags.append("Acoustic")

        characteristics["tags"] = tags
        characteristics["total_duration_ms"] = sum(t.get("duration_ms", 0) for t in tracks)
        return characteristics

    def _apply_novelty_labels(self, tracks: List[dict], library_tracks: List[dict]) -> List[dict]:
        library_artists = self._artist_tokens(library_tracks)
        seen_discovery_artists = set()
        relabeled = 0

        for track in tracks:
            novelty = self._novelty_score(track, library_artists)
            track["novelty_score"] = novelty
            primary_artist = self._primary_artist(track)
            if novelty < 0.42:
                track["source"] = "library"
                relabeled += 1
            elif primary_artist in seen_discovery_artists:
                track["source"] = "library"
                relabeled += 1
            else:
                track["source"] = "discovery"
                seen_discovery_artists.add(primary_artist)

        print(f"[playlist.discovery.truth] total={len(tracks)} relabeled_to_library={relabeled}")
        return tracks

    def _novelty_score(self, track: dict, library_artists: set) -> float:
        primary_artist = self._primary_artist(track)
        artist_unfamiliarity = 0.0 if primary_artist in library_artists else 1.0
        popularity = max(0, min(track.get("popularity", 0), 100)) / 100
        popularity_dampening = 1.0 - min(0.65, popularity * 0.65)
        if track.get("preferred_artist_score", 0) and primary_artist in library_artists:
            artist_unfamiliarity = 0.15
        embedding_distance_proxy = 0.35 + 0.45 * artist_unfamiliarity + 0.20 * track.get("region_confidence", 0.5)
        return self._clamp(embedding_distance_proxy * artist_unfamiliarity * popularity_dampening)

    def _suppress_duplicate_discovery_artists(self, scored_tracks: List[dict]) -> List[dict]:
        selected = []
        seen_artists = set()
        suppressed = 0
        for item in scored_tracks:
            artist = self._primary_artist(item["track"])
            if artist and artist in seen_artists:
                suppressed += 1
                continue
            seen_artists.add(artist)
            selected.append(item)
        if suppressed:
            print(f"[playlist.discovery.artist_suppression] suppressed={suppressed}")
        return selected

    def _internal_discovery_tracks(self, region_key: str, mood: Optional[str]) -> List[dict]:
        source_pool = CALM_DISCOVERY_POOLS if (mood or "").lower().strip() == "calm" else INTERNAL_DISCOVERY_POOLS
        seeds = source_pool.get(region_key) or source_pool.get("global_english") or []
        return self._build_seed_tracks(seeds, region_key, "internal_discovery", "discovery", mood)

    def _mood_safe_internal_tracks(self, region_key: str, mood: str, source: str) -> List[dict]:
        if mood.lower().strip() == "calm":
            pool = CALM_FAMILIAR_SEEDS if source == "library" else CALM_DISCOVERY_POOLS
        else:
            pool = CURATED_FAMILIAR_SEEDS if source == "library" else INTERNAL_DISCOVERY_POOLS
        seeds = pool.get(region_key) or pool.get("global_english") or []
        return self._build_seed_tracks(seeds, region_key, f"mood_{source}", source, mood)

    def _curated_familiar_seed_tracks(self, region_key: str, mood: Optional[str] = None) -> List[dict]:
        source_pool = CALM_FAMILIAR_SEEDS if (mood or "").lower().strip() == "calm" else CURATED_FAMILIAR_SEEDS
        seeds = source_pool.get(region_key) or source_pool["global_english"]
        return self._build_seed_tracks(seeds, region_key, "seed", "library", mood)

    def _build_seed_tracks(
        self,
        seeds: List[tuple],
        region_key: str,
        namespace: str,
        source: str,
        mood: Optional[str],
    ) -> List[dict]:
        tracks = []
        for index, (name, artist, popularity, duration_ms) in enumerate(seeds):
            track_id = f"{namespace}:{region_key}:{index}:{name}".lower().replace(" ", "_")
            track = {
                "id": track_id,
                "name": name,
                "artist": artist,
                "album": f"{region_key.replace('_', ' ').title()} {namespace.replace('_', ' ').title()}",
                "duration_ms": duration_ms,
                "popularity": popularity,
                "uri": "",
                "external_url": "",
                "preview_url": None,
                "source": source,
                "region_confidence": 0.95,
                "quality_score": 0.85,
                "novelty_score": 0.85 if source == "discovery" else 0.0,
            }
            track.update(self._heuristic_audio_features(track))
            if (mood or "").lower().strip() == "calm":
                track.update({
                    "danceability": min(track.get("danceability", 0.5), 0.52),
                    "energy": min(track.get("energy", 0.5), 0.48),
                    "valence": min(max(track.get("valence", 0.5), 0.35), 0.68),
                    "tempo": min(track.get("tempo", 118), 126),
                })
            track["feature_source"] = "curated_heuristic"
            tracks.append(track)
        return tracks

    def _artist_tokens(self, tracks: List[dict]) -> set:
        return {self._primary_artist(track) for track in tracks if self._primary_artist(track)}

    def _primary_artist(self, track: dict) -> str:
        artist = track.get("primary_artist_normalized")
        if artist:
            return str(artist)
        return normalize_artist_name(str(track.get("artist", "")).split(",")[0])

    def _generate_regional_playlist_name(self, region_key: str, cluster_id: int, mood: Optional[str]) -> str:
        region_names = {
            "india_hindi": "Hindi",
            "india_tamil": "Tamil",
            "india_punjabi": "Punjabi",
            "arab_world": "Arabic",
            "latin_america": "Latin",
            "south_korea": "K-Pop",
            "japan": "J-Pop",
            "nigeria": "Afrobeats",
            "brazil": "Brazilian",
            "france": "French",
            "global_english": "Global",
            "global_spanish": "Spanish",
            "global_arabic": "Arabic Pop",
        }
        region_display = region_names.get(region_key, region_key.replace("_", " ").title())
        return f"{region_display} {mood.title()} Journey" if mood else f"{region_display} Discovery Mix"

    def _generate_regional_description(self, region_key: str, characteristics: dict, mood: Optional[str]) -> str:
        region_display = region_key.replace("_", " ").title()
        discovery_count = characteristics.get("discovery_count", 0)
        library_count = characteristics.get("library_count", 0)
        desc = f"Your personalized {region_display} playlist: {library_count} familiar tracks + {discovery_count} discoveries"
        tags = characteristics.get("tags", [])
        if tags:
            desc += f". {', '.join(tags[:2])}."
        if mood:
            desc += f" Curated for a {mood} vibe."
        return desc

    def _track_text(self, track: dict) -> str:
        return " ".join([
            str(track.get("name", "")),
            str(track.get("artist", "")),
            str(track.get("album", "")),
            str(track.get("search_query", "")),
        ]).lower()

    def _track_key(self, track: dict) -> str:
        return str(
            track.get("track_fingerprint")
            or track.get("id")
            or track_fingerprint(track.get("name", ""), track.get("artist", ""))
        ).lower()

    def _request_seed(self, region_key: str, cluster_id: int) -> int:
        serial = self.__class__.request_serial_by_region.get(region_key, 0) + 1
        self.__class__.request_serial_by_region[region_key] = serial
        current_time_bucket = int(time.time() * 1000 // 250) + serial
        seed_input = f"{region_key}:{cluster_id}:{current_time_bucket}"
        return int(hashlib.sha1(seed_input.encode()).hexdigest()[:8], 16)

    def _apply_recent_memory_penalty(self, scored_tracks: List[dict], region_key: str) -> List[dict]:
        recent_ids = set(self.__class__.recently_served_track_ids.get(region_key, []))
        if not recent_ids:
            return scored_tracks

        penalized = []
        for item in scored_tracks:
            track = item["track"]
            key = self._track_key(track)
            adjusted = item["score"] - 0.12 if key in recent_ids else item["score"]
            penalized.append({"track": track, "score": adjusted})
        penalized.sort(key=lambda x: x["score"], reverse=True)
        return penalized

    def _apply_request_seeded_diversity(
        self,
        scored_tracks: List[dict],
        region_key: str,
        cluster_id: int,
    ) -> List[dict]:
        if len(scored_tracks) <= 3:
            return scored_tracks

        ranked = sorted(scored_tracks, key=lambda x: x["score"], reverse=True)
        top_fixed = ranked[:2]
        remainder = ranked[2:]
        if not remainder:
            return ranked

        seed = self._request_seed(region_key, cluster_id)
        rng = random.Random(seed)

        score_values = [item["score"] for item in remainder]
        span = max(score_values) - min(score_values) if len(score_values) > 1 else 0.0
        band_width = max(0.02, span / 4) if span else 0.02

        bands = {}
        band_order = []
        top_score = score_values[0]
        for item in remainder:
            band_index = int((top_score - item["score"]) / band_width)
            if band_index not in bands:
                bands[band_index] = []
                band_order.append(band_index)
            bands[band_index].append(item)

        middle = []
        for band_index in sorted(band_order):
            band_items = bands[band_index]
            rng.shuffle(band_items)
            middle.extend(band_items)

        tail_size = max(1, len(middle) // 3)
        tail = middle[-tail_size:]
        middle_core = middle[:-tail_size]
        if len(tail) > 1:
            rotate_by = seed % len(tail)
            tail = tail[rotate_by:] + tail[:rotate_by]

        diversified = top_fixed + middle_core + tail
        front_window = diversified[2:6]
        if len(front_window) > 1:
            rotate_by = seed % len(front_window)
            front_window = front_window[rotate_by:] + front_window[:rotate_by]
            diversified = diversified[:2] + front_window + diversified[6:]

        return diversified

    def _remember_served_tracks(self, region_key: str, tracks: List[dict]) -> None:
        memory = self.__class__.recently_served_track_ids.get(region_key, [])
        for track in tracks:
            track_id = self._track_key(track)
            if track_id in memory:
                memory.remove(track_id)
            memory.append(track_id)
        if len(memory) > self.__class__.recent_window_size:
            memory = memory[-self.__class__.recent_window_size:]
        self.__class__.recently_served_track_ids[region_key] = memory

    def _clamp(self, value: float, low: float = 0.0, high: float = 1.0) -> float:
        return max(low, min(high, value))
