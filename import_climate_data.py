#!/usr/bin/env python3
"""
Import climate data from multiple sources into the unified climate_ingredients table.

Sources (in priority order):
1. Danish DB (Den Store Klimadatabase) - highest confidence, has nutrition
2. Agribalyse (French/EU) - high confidence, no nutrition
3. HESTIA (Global) - medium confidence (future)

Run: python import_climate_data.py
"""

import pandas as pd
from db import get_connection, init_db


def clear_climate_ingredients():
    """Clear existing data (for fresh import)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('DELETE FROM climate_ingredients')
    conn.commit()
    cur.close()
    conn.close()
    print("Cleared existing climate_ingredients data")


def import_danish_db():
    """Import Danish climate database (highest confidence, has nutrition).

    Uses climate_data.xlsx which has BOTH English and Danish names.
    """
    print("\n=== Importing Danish DB ===")

    # Use climate_data.xlsx which has English 'Name' column + Danish 'Navn' column
    df = pd.read_excel('climate_data.xlsx', sheet_name='DK')
    print(f"Loaded {len(df)} rows from climate_data.xlsx (has EN + DK names)")

    conn = get_connection()
    cur = conn.cursor()

    imported = 0
    skipped = 0

    for _, row in df.iterrows():
        try:
            # Extract values, handling NaN
            # climate_data.xlsx has 'Name' (English) and 'Navn' (Danish)
            name_en = str(row['Name']) if pd.notna(row.get('Name')) else None
            name_dk = str(row['Navn']) if pd.notna(row.get('Navn')) else None
            co2 = float(row['Total kg CO2-eq/kg']) if pd.notna(row.get('Total kg CO2-eq/kg')) else None

            if (not name_en and not name_dk) or co2 is None:
                skipped += 1
                continue

            # Nutrition data
            energy_kj = float(row['Energy (KJ/100 g)']) if pd.notna(row.get('Energy (KJ/100 g)')) else None
            fat = float(row['Fat (g/100 g)']) if pd.notna(row.get('Fat (g/100 g)')) else None
            carbs = float(row['Carbohydrate (g/100 g)']) if pd.notna(row.get('Carbohydrate (g/100 g)')) else None
            protein = float(row['Protein (g/100 g)']) if pd.notna(row.get('Protein (g/100 g)')) else None

            # Category
            category = str(row['Category']) if pd.notna(row.get('Category')) else None
            subcategory = str(row['DSK Kategori']) if pd.notna(row.get('DSK Kategori')) else None

            # Source ID
            source_id = str(row['ID_Ra']) if pd.notna(row.get('ID_Ra')) else None

            cur.execute('''
                INSERT INTO climate_ingredients
                (name_en, name_dk, name_fr, co2_per_kg, source_db, source_id, confidence,
                 category, subcategory, energy_kj, fat_g, carbs_g, protein_g)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                name_en,  # Now we have English names!
                name_dk,
                None,  # name_fr
                co2,
                'danish',
                source_id,
                'highest',  # Danish DB is our primary source
                category,
                subcategory,
                energy_kj,
                fat,
                carbs,
                protein
            ))
            imported += 1

        except Exception as e:
            print(f"Error importing row: {e}")
            skipped += 1

    conn.commit()
    cur.close()
    conn.close()

    print(f"Imported: {imported}, Skipped: {skipped}")
    return imported


def import_agribalyse():
    """Import Agribalyse database (high confidence, no nutrition)."""
    print("\n=== Importing Agribalyse ===")

    df = pd.read_excel(
        'AGRIBALYSE3.2_Tableur produits alimentaires_PublieAOUT25.xlsx',
        sheet_name='Synthese',
        header=2
    )
    print(f"Loaded {len(df)} rows from Agribalyse")

    conn = get_connection()
    cur = conn.cursor()

    imported = 0
    skipped = 0

    for _, row in df.iterrows():
        try:
            # Column names (with line breaks in some)
            name_fr = str(row['Nom du Produit en Français']) if pd.notna(row.get('Nom du Produit en Français')) else None
            name_en = str(row['LCI Name']) if pd.notna(row.get('LCI Name')) else None
            co2 = float(row['kg CO2 eq/kg de produit']) if pd.notna(row.get('kg CO2 eq/kg de produit')) else None

            if not name_fr or co2 is None:
                skipped += 1
                continue

            # Skip header row if it got included
            if name_fr == 'Nom du Produit en Français' or str(co2) == 'kg CO2 eq/kg de produit':
                skipped += 1
                continue

            # Category
            category = str(row["Groupe d'aliment"]) if pd.notna(row.get("Groupe d'aliment")) else None
            subcategory = str(row["Sous-groupe d'aliment"]) if pd.notna(row.get("Sous-groupe d'aliment")) else None

            # Source ID (Agribalyse code)
            source_id = str(row['Code\nAGB']) if pd.notna(row.get('Code\nAGB')) else None

            cur.execute('''
                INSERT INTO climate_ingredients
                (name_en, name_dk, name_fr, co2_per_kg, source_db, source_id, confidence,
                 category, subcategory, energy_kj, fat_g, carbs_g, protein_g)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                name_en,
                None,  # name_dk
                name_fr,
                co2,
                'agribalyse',
                source_id,
                'high',  # Agribalyse is our secondary source
                category,
                subcategory,
                None, None, None, None  # No nutrition in Agribalyse
            ))
            imported += 1

        except Exception as e:
            print(f"Error importing row: {e}")
            skipped += 1

    conn.commit()
    cur.close()
    conn.close()

    print(f"Imported: {imported}, Skipped: {skipped}")
    return imported


def get_stats():
    """Show statistics about imported data."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute('SELECT source_db, COUNT(*) FROM climate_ingredients GROUP BY source_db')
    results = cur.fetchall()

    cur.execute('SELECT COUNT(*) FROM climate_ingredients')
    total = cur.fetchone()[0]

    cur.close()
    conn.close()

    print("\n=== Import Statistics ===")
    for source, count in results:
        print(f"  {source}: {count} ingredients")
    print(f"  TOTAL: {total} ingredients")
    return total


def dry_run():
    """Test parsing without database - shows sample data from each source."""
    print("\n=== DRY RUN MODE (no database required) ===\n")

    # Test Danish DB parsing
    print("--- Danish DB Sample ---")
    df_dk = pd.read_excel('climate_data_DK.xlsx', sheet_name='DK')
    print(f"Total rows: {len(df_dk)}")
    for i, row in df_dk.head(3).iterrows():
        print(f"  {row['Navn']}: {row['Total kg CO2e/kg']} kg CO2/kg")

    # Test Agribalyse parsing
    print("\n--- Agribalyse Sample ---")
    df_agri = pd.read_excel(
        'AGRIBALYSE3.2_Tableur produits alimentaires_PublieAOUT25.xlsx',
        sheet_name='Synthese',
        header=2
    )
    print(f"Total rows: {len(df_agri)}")
    for i, row in df_agri.head(3).iterrows():
        name = row.get('Nom du Produit en Français', 'N/A')
        name_en = row.get('LCI Name', 'N/A')
        co2 = row.get('kg CO2 eq/kg de produit', 'N/A')
        print(f"  {name} ({name_en}): {co2} kg CO2/kg")

    print("\n--- Summary ---")
    print(f"Danish DB: {len(df_dk)} ingredients (with nutrition)")
    print(f"Agribalyse: {len(df_agri)} ingredients (CO2 only)")
    print(f"TOTAL: {len(df_dk) + len(df_agri)} ingredients available for import")


if __name__ == '__main__':
    import sys

    print("Climate Data Import Script")
    print("=" * 40)

    # Check for dry-run mode
    if '--dry-run' in sys.argv:
        dry_run()
        sys.exit(0)

    # Full import mode - requires DATABASE_URL
    print("Running full import (requires DATABASE_URL)...")
    print("Use --dry-run to test parsing without database\n")

    # Initialize database tables
    init_db()

    # Clear existing data for fresh import
    clear_climate_ingredients()

    # Import from each source
    danish_count = import_danish_db()
    agribalyse_count = import_agribalyse()

    # Show final stats
    total = get_stats()

    print("\n" + "=" * 40)
    print("Import complete!")
    print(f"Total ingredients available: {total}")
