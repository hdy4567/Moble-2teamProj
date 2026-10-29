"""Editorial product guidance only. Never supplies SQL catalog values."""
import json
import logging
from pathlib import Path

GUIDE_PATH=Path(__file__).with_name('data')/'product_guides.json'
SOURCES={
    'fda':('FDA · 신선 농산물 취급 안내','https://www.fda.gov/food/buy-store-serve-safe-food/selecting-and-serving-produce-safely'),
    'vegetables':('미네소타대학교 · 채소 보관 안내','https://extension.umn.edu/garden-and-home/yard-and-garden/gardening-in-minnesota/harvesting-and-storing-home-garden-vegetables'),
    'washing':('미네소타대학교 · 과일·채소 세척 안내','https://extension.umn.edu/food/preparing/cooking-at-home/washing-fresh-fruits-and-vegetables'),
    'blueberry':('미네소타대학교 · 블루베리 안내','https://reallifegoodfood.umn.edu/fruits/blueberries'),
    'apple':('아이오와주립대학교 · 사과 안내','https://spendsmart.extension.iastate.edu/produce-item/apples/'),
    'grape':('UC Davis · 포도 보관 안내','https://postharvest.ucdavis.edu/produce-facts-sheets/grape'),
}


def load_guides(path=GUIDE_PATH):
    try:
        document=json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if not isinstance(document,dict) or document.get('version')!=1 or not isinstance(document.get('products'),dict):
            raise ValueError('Invalid product guide document')
        result={}
        for key, entry in document['products'].items():
            if not key.isascii() or not key.isdigit() or not isinstance(entry,dict):continue
            fields=('summary','storage','preparation','serving')
            if not all(isinstance(entry.get(field),str) and 0<len(entry[field])<=500 for field in fields):continue
            names=entry.get('names')
            source_ids=entry.get('sources')
            if not isinstance(names,list) or not names or not all(isinstance(n,str) and 0<len(n)<=100 for n in names):continue
            if not isinstance(source_ids,list) or not source_ids or not all(isinstance(s,str) and s in SOURCES for s in source_ids):continue
            # Whitelist fields; never read editorial price/stock/origin/expiry values.
            result[key]={field:entry[field] for field in fields}
            result[key]['names']=names
            result[key]['sources']=[SOURCES[s] for s in dict.fromkeys(source_ids)]
        return result
    except (OSError,ValueError,TypeError):
        logging.getLogger(__name__).warning('상품 설명 파일 확인 필요; 상품별 안내를 표시하지 않습니다.')
        return {}


def guide_for(product, guides):
    entry=guides.get(str(product['product_id']))
    if not entry:return None
    normalize=lambda text: ''.join(str(text).split()).casefold()
    if normalize(product.get('name','')) not in {normalize(n) for n in entry['names']}:
        return None  # Reused product IDs / renamed foods must not inherit old tips.
    return entry
