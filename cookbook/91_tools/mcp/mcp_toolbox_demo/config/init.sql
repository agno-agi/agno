-- Create the hotels table
CREATE TABLE hotels(
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR NOT NULL,
    location VARCHAR NOT NULL,
    price_tier VARCHAR NOT NULL,
    checkin_date DATE NOT NULL,
    checkout_date DATE NOT NULL,
    booked BIT NOT NULL
);

-- Insert the hotel data with corrected tier names and valid 2025/2026 dates
INSERT INTO hotels(id, name, location, price_tier, checkin_date, checkout_date, booked) VALUES
-- Luxury Hotels
(1, 'Hilton Basel', 'Basel', 'Luxury', '2025-11-01', '2025-11-30', B'0'),
(2, 'InterContinental Geneva', 'Geneva', 'Luxury', '2025-12-15', '2025-12-20', B'0'),
(3, 'Fairmont Le Montreux Palace', 'Montreux', 'Luxury', '2026-01-10', '2026-01-15', B'0'),
(4, 'The Ritz-Carlton Zurich', 'Zurich', 'Luxury', '2025-10-20', '2025-10-25', B'0'),
(5, 'Grand Hotel Kempinski Geneva', 'Geneva', 'Luxury', '2025-11-25', '2025-11-30', B'0'),

-- Economy Hotels  
(6, 'Best Western Bern', 'Bern', 'Economy', '2025-10-15', '2025-10-18', B'0'),
(7, 'Holiday Inn Basel', 'Basel', 'Economy', '2025-11-08', '2025-11-12', B'0'),
(8, 'Comfort Inn Zurich', 'Zurich', 'Economy', '2025-12-01', '2025-12-05', B'0'),
(9, 'Ibis Budget Geneva', 'Geneva', 'Economy', '2026-01-05', '2026-01-08', B'0'),
(10, 'easyHotel Zurich', 'Zurich', 'Economy', '2025-10-28', '2025-10-31', B'0'),

-- Boutique Hotels
(11, 'Hotel Widder Zurich', 'Zurich', 'Boutique', '2025-11-12', '2025-11-16', B'0'),
(12, 'The Dolder Grand', 'Zurich', 'Boutique', '2025-12-08', '2025-12-12', B'0'),
(13, 'Boutique Hotel Bellevue Basel', 'Basel', 'Boutique', '2026-01-20', '2026-01-24', B'0'),
(14, 'Hotel Villa Honegg', 'Ennetbürgen', 'Boutique', '2025-11-03', '2025-11-07', B'0'),
(15, 'The Omnia Zermatt', 'Zermatt', 'Boutique', '2025-12-22', '2025-12-28', B'0'),

-- Extended-Stay Hotels
(16, 'Residence Inn Zurich', 'Zurich', 'Extended-Stay', '2025-10-01', '2025-10-31', B'0'),
(17, 'Extended Stay Geneva', 'Geneva', 'Extended-Stay', '2025-11-01', '2025-12-01', B'0'),
(18, 'Aparthotel Adagio Basel', 'Basel', 'Extended-Stay', '2025-12-01', '2026-01-15', B'0'),
(19, 'Homewood Suites Bern', 'Bern', 'Extended-Stay', '2026-01-01', '2026-02-01', B'0'),
(20, 'Element Zurich Airport', 'Zurich', 'Extended-Stay', '2025-11-15', '2025-12-15', B'0'),

-- New York Hotels (to match the Python example)
(21, 'The Plaza New York', 'New York', 'Luxury', '2025-10-10', '2025-10-15', B'0'),
(22, 'Marriott Times Square', 'New York', 'Luxury', '2025-11-20', '2025-11-25', B'0'),
(23, 'Pod Hotel Brooklyn', 'New York', 'Economy', '2025-12-05', '2025-12-08', B'0'),
(24, 'The High Line Hotel', 'New York', 'Boutique', '2025-10-25', '2025-10-30', B'0'),
(25, 'Residence Inn Manhattan', 'New York', 'Extended-Stay', '2025-11-01', '2025-12-01', B'0'),

-- Paris Hotels
(26, 'The Ritz Paris', 'Paris', 'Luxury', '2025-10-18', '2025-10-22', B'0'),
(27, 'Hotel Malte Opera', 'Paris', 'Economy', '2025-11-28', '2025-12-02', B'0'),
(28, 'Hotel des Grands Boulevards', 'Paris', 'Boutique', '2025-12-10', '2025-12-14', B'0'),
(29, 'Citadines Bastille Paris', 'Paris', 'Extended-Stay', '2026-01-08', '2026-02-08', B'0'),

-- Tokyo Hotels
(30, 'The Peninsula Tokyo', 'Tokyo', 'Luxury', '2025-10-12', '2025-10-17', B'0'),
(31, 'Capsule Hotel Anshin Oyado', 'Tokyo', 'Economy', '2025-11-18', '2025-11-21', B'0'),
(32, 'Aman Tokyo', 'Tokyo', 'Boutique', '2025-12-18', '2025-12-23', B'0'),
(33, 'Oakwood Premier Tokyo', 'Tokyo', 'Extended-Stay', '2025-11-05', '2025-12-05', B'0');