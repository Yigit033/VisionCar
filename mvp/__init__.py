"""VisionCar Sürüm 1.0 MVP — kademeli şarj tespiti iskeleti.

Kademe: araç tespiti (COCO yolo11s, class=2) -> tabanca tespiti (kademe1_gun.pt)
-> containment kararı (tabanca merkezi araç kutusunun içinde mi) -> çift yönlü
debounce -> durum (ŞARJ AKTİF / BEKLENİYOR).

Karar mantığı (debounce.py, charge_logic.py) görselleştirmeden BAĞIMSIZDIR.
"""
