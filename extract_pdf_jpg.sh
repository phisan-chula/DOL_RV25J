#!/bin/bash

PDF="Narathiwas.pdf"

# เช็คว่ามีไฟล์ต้นฉบับไหม
if [ ! -f "$PDF" ]; then
    echo "❌ ERROR: File $PDF not found"
    exit 1
fi

for i in $(seq 8 15); do
    PAGE=$(printf "%02d" "$i")      # 08, 09, ...
    FOLDER="p$PAGE"                 # p08, p09, ...
    
    echo "---------------------------------------------"
    echo "▶ Processing page $i → folder $FOLDER/"

    mkdir -p "$FOLDER"

    ONEPAGE_PDF="$FOLDER/$FOLDER.pdf"          # p08/p08.pdf
    JPG_BASE="$FOLDER/$FOLDER"                 # p08/p08
    JPG_TMP="${JPG_BASE}-1.jpg"                # p08/p08-1.jpg
    JPG_FINAL="${FOLDER}/${FOLDER}_rv25j.jpg"  # p08/p08_rv25j.jpg

    # 1) แยกหน้าเดียวเป็น PDF
    pdfseparate -f "$i" -l "$i" "$PDF" "$ONEPAGE_PDF"
    if [ $? -ne 0 ]; then
        echo "❌ pdfseparate failed on page $i"
        continue
    fi

    # 2) แปลง PDF หน้านั้นเป็น JPG 300 dpi
    pdftoppm "$ONEPAGE_PDF" "$JPG_BASE" -jpeg -r 300
    if [ $? -ne 0 ]; then
        echo "❌ pdftoppm failed on $ONEPAGE_PDF"
        continue
    fi

    # 3) rename p08-1.jpg → p08_rv25j.jpg
    if [ -f "$JPG_TMP" ]; then
        mv "$JPG_TMP" "$JPG_FINAL"
        echo "✔ Created $JPG_FINAL"
    else
        echo "⚠ WARNING: $JPG_TMP not found"
    fi

    # 4) ลบ PDF หน้าเดี่ยวทิ้ง
    rm -f "$ONEPAGE_PDF"
    echo "🗑 Removed $ONEPAGE_PDF"

done

echo "============================================="
echo "🎉 Done: pages 8–15 → p??/p??_rv25j.jpg"

