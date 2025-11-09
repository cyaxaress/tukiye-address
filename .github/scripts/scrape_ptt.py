#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import json
import time
import html
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import requests
from bs4 import BeautifulSoup


class PTTAddressScraper:
    """Scrapes Turkish address data (il/ilce/mahalle) from PTT website."""

    BASE_URL = 'https://postakodu.ptt.gov.tr'

    # Turkish lowercase mapping
    TURKISH_LOWERCASE = {
        'İ': 'i',
        'I': 'ı',
        'Ğ': 'ğ',
        'Ş': 'ş',
        'Ç': 'ç',
        'Ö': 'ö',
        'Ü': 'ü',
    }

    def __init__(self):
        """Initialize HTTP session with cookie jar and headers."""
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        })
        self.total_neighborhoods = 0

    def capitalize_first_letter(self, text: str) -> str:
        """
        Capitalize first letter of each word, handling Turkish characters.
        Example: "İSTANBUL" -> "İstanbul", "KADIKÖY" -> "Kadıköy"
        """
        words = text.strip().split()
        capitalized_words = []

        for word in words:
            if not word:
                continue

            # Get first character and rest of the word
            first_char = word[0]
            rest = word[1:]

            # Lowercase the rest, handling Turkish characters
            rest_lowercased = ''
            for char in rest:
                if char in self.TURKISH_LOWERCASE:
                    rest_lowercased += self.TURKISH_LOWERCASE[char]
                else:
                    rest_lowercased += char.lower()

            # First character stays uppercase (already is)
            capitalized_words.append(first_char + rest_lowercased)

        return ' '.join(capitalized_words)

    def clean_text(self, text: str) -> str:
        """Clean and format text, handling HTML entities and Turkish capitalization."""
        # Decode HTML entities
        text = html.unescape(text)

        # Trim whitespace
        text = text.strip()

        # Replace multiple spaces with single space
        text = re.sub(r'\s+', ' ', text)

        # Capitalize first letter of each word (Turkish-aware)
        text = self.capitalize_first_letter(text)

        return text

    def clean_id(self, id_str: str) -> str:
        """Clean ID string, replacing special characters."""
        id_str = id_str.replace('\\', '_').replace('/', '_')
        id_str = re.sub(r'[^a-zA-Z0-9_]', '', id_str)
        return id_str

    def extract_viewstate_and_validation(self, html: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract __VIEWSTATE and __EVENTVALIDATION from HTML."""
        viewstate_match = re.search(r'__VIEWSTATE" value="([^"]+)"', html)
        eventvalidation_match = re.search(r'__EVENTVALIDATION" value="([^"]+)"', html)

        viewstate = viewstate_match.group(1) if viewstate_match else None
        eventvalidation = eventvalidation_match.group(1) if eventvalidation_match else None

        return viewstate, eventvalidation

    def get_provinces(self, html: str) -> List[Tuple[str, str]]:
        """Extract provinces (il) from the initial page."""
        # Match the province dropdown
        province_match = re.search(
            r'MainContent_DropDownList1".*?>(.*?)</select>',
            html,
            re.DOTALL
        )

        if not province_match:
            raise Exception('İl listesi bulunamadı')

        province_select = province_match.group(1)

        # Extract all option values
        option_pattern = r'<option value="(\d+)">([^<]+)</option>'
        matches = re.findall(option_pattern, province_select)

        # Filter out the default option (-1)
        provinces = [(id, name) for id, name in matches if id != '-1']

        return provinces

    def get_districts(self, province_id: str, html: str) -> List[Tuple[str, str]]:
        """Extract districts (ilce) for a given province."""
        # Match the district dropdown
        district_match = re.search(
            r'MainContent_DropDownList2".*?>(.*?)</select>',
            html,
            re.DOTALL
        )

        if not district_match:
            return []

        district_select = district_match.group(1)

        # Extract all option values
        option_pattern = r'<option value="(\d+)">([^<]+)</option>'
        matches = re.findall(option_pattern, district_select)

        # Filter out the default option (-1)
        districts = [(id, name) for id, name in matches if id != '-1']

        return districts

    def get_neighborhoods(
        self,
        province_id: str,
        district_id: str,
        district_html: str
    ) -> List[Dict[str, str]]:
        """Get neighborhoods (mahalle) for a given district."""
        viewstate, eventvalidation = self.extract_viewstate_and_validation(district_html)

        if not viewstate or not eventvalidation:
            return []

        # POST to get neighborhoods
        form_data = {
            '__EVENTTARGET': 'ctl00$MainContent$DropDownList2',
            '__EVENTARGUMENT': '',
            '__VIEWSTATE': viewstate,
            '__EVENTVALIDATION': eventvalidation,
            'ctl00$MainContent$DropDownList1': province_id,
            'ctl00$MainContent$DropDownList2': district_id,
        }

        response = self.session.post(self.BASE_URL, data=form_data)
        response.raise_for_status()
        neighborhood_html = response.text

        # Match the neighborhood dropdown
        neighborhood_match = re.search(
            r'MainContent_DropDownList3".*?>(.*?)</select>',
            neighborhood_html,
            re.DOTALL
        )

        if not neighborhood_match:
            return []

        neighborhood_select = neighborhood_match.group(1)

        # Extract all option values
        option_pattern = r'<option value="([^"]+)">([^<]+)</option>'
        matches = re.findall(option_pattern, neighborhood_select)

        neighborhoods = []
        district_source_id = f"{province_id}_{district_id}"

        for neighborhood_id, neighborhood_name in matches:
            if neighborhood_id == '-1':
                continue

            # Clean the neighborhood name
            cleaned_name = self.clean_text(neighborhood_name)

            # Extract postal code (5 digits)
            postal_code_match = re.search(r'(\d{5})', cleaned_name)
            postal_code = postal_code_match.group(1) if postal_code_match else None

            # Remove postal code and everything after "/" from name
            cleaned_name = re.sub(r'\s*/\s*.*$', '', cleaned_name)

            # Clean the ID
            mahalle_id = self.clean_id(neighborhood_id)

            neighborhoods.append({
                'mahalle_id': mahalle_id,
                'mahalle_adi': cleaned_name,
                'posta_kodu': postal_code,
            })

            self.total_neighborhoods += 1

        return neighborhoods

    def scrape(self) -> List[Dict]:
        """Main scraping method that orchestrates the entire process."""
        print("PTT Adres Verisi Çekme İşlemi Başlatılıyor")

        address_data = []

        # Get initial page
        response = self.session.get(self.BASE_URL)
        response.raise_for_status()
        html = response.text

        # Get all provinces
        provinces = self.get_provinces(html)
        total_provinces = len(provinces)

        print(f"Toplam {total_provinces} il bulundu.")

        # Extract initial viewstate and eventvalidation
        viewstate, eventvalidation = self.extract_viewstate_and_validation(html)

        if not viewstate or not eventvalidation:
            raise Exception('__VIEWSTATE veya __EVENTVALIDATION bulunamadı')

        # Process each province
        for province_index, (province_id, province_name_raw) in enumerate(provinces, 1):
            province_name = self.clean_text(province_name_raw)

            print(f"\n[{province_index}/{total_provinces}] {province_name} ili işleniyor...")

            # POST to get districts for this province
            form_data = {
                '__EVENTTARGET': 'ctl00$MainContent$DropDownList1',
                '__EVENTARGUMENT': '',
                '__VIEWSTATE': viewstate,
                '__EVENTVALIDATION': eventvalidation,
                'ctl00$MainContent$DropDownList1': province_id,
            }

            response = self.session.post(self.BASE_URL, data=form_data)
            response.raise_for_status()
            district_html = response.text

            # Update viewstate and eventvalidation for next requests
            viewstate, eventvalidation = self.extract_viewstate_and_validation(district_html)

            # Get districts for this province
            districts = self.get_districts(province_id, district_html)
            total_districts = len(districts)

            print(f"  {total_districts} ilçe bulundu.")

            current_province = {
                'il_id': province_id,
                'il_adi': province_name,
                'ilceler': [],
            }

            # Process each district
            for district_index, (district_id, district_name_raw) in enumerate(districts, 1):
                district_name = self.clean_text(district_name_raw)

                print(f"  [{district_index}/{total_districts}] {district_name} ilçesi işleniyor...")

                # Get neighborhoods for this district
                neighborhoods = self.get_neighborhoods(
                    province_id,
                    district_id,
                    district_html
                )

                current_province['ilceler'].append({
                    'ilce_id': district_id,
                    'ilce_adi': district_name,
                    'mahalleler': neighborhoods,
                })

                # Update the address data
                if not address_data:
                    address_data.append(current_province)
                else:
                    last_index = len(address_data) - 1
                    if address_data[last_index]['il_id'] == province_id:
                        address_data[last_index] = current_province
                    else:
                        address_data.append(current_province)

                # Small delay to avoid rate limiting
                time.sleep(1)

            # Delay between provinces
            time.sleep(2)

            # Note: viewstate and eventvalidation will be extracted from the next province's district_html

        print(f"\n\nİşlem tamamlandı!")
        print(f"Toplam {total_provinces} il ve {self.total_neighborhoods} mahalle verisi çekildi.")

        return address_data

    def save_to_file(self, data: List[Dict], filename: str):
        """Save data to JSON file with UTF-8 encoding."""
        # Create PTT directory if it doesn't exist
        ptt_dir = 'PTT'
        os.makedirs(ptt_dir, exist_ok=True)
        
        # Join the directory path with the filename
        filepath = os.path.join(ptt_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

    def update_readme(self, readme_path: str = 'README.md'):
        """Update README with last updated date."""
        if not os.path.exists(readme_path):
            print(f"README dosyası bulunamadı: {readme_path}")
            return

        # Read current README
        with open(readme_path, 'r', encoding='utf-8') as f:
            readme_content = f.read()

        # Get current date and time in Turkish format
        now = datetime.now()
        # Format: "15 Ocak 2024, 14:30" (Turkish month names)
        turkish_months = [
            'Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran',
            'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'
        ]
        formatted_date = f"{now.day} {turkish_months[now.month - 1]} {now.year}, {now.hour:02d}:{now.minute:02d}"

        # Replace the date in the last updated section
        last_updated_pattern = r'(## 📅 Son Güncelleme\s*\n\s*\*\*Son güncelleme:\*\*)[^\n]+'
        readme_content = re.sub(
            last_updated_pattern,
            f'\\1 {formatted_date}',
            readme_content,
            flags=re.MULTILINE
        )

        # Write updated README
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write(readme_content)

        print(f"README güncellendi: Son güncelleme tarihi eklendi ({formatted_date})")


def main():
    """Main entry point."""
    scraper = PTTAddressScraper()

    try:
        # Scrape the data
        address_data = scraper.scrape()

        filename = f'ptt_il_ilce_mahalle.json'

        # Save to file
        scraper.save_to_file(address_data, filename)

        print(f"\nVeriler PTT/{filename} dosyasına kaydedildi.")

        # Update README with last updated date
        scraper.update_readme()

    except Exception as e:
        print(f"Hata: {e}")
        raise


if __name__ == '__main__':
    main()

