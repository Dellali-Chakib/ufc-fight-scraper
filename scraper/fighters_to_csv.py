import csv

def write_csv(fighters):
    # Specify the file name
    file_name = "output.csv"

    # Writing to the CSV file
    with open(file_name, mode="w", newline="", encoding="utf-8") as file:
        # Create a writer object
        writer = csv.DictWriter(file, fieldnames=fighters)
        
        # Write the header row
        writer.writeheader()
        
        # Write the data rows
        writer.writerows(fighters)

    print(f"CSV file '{file_name}' has been created successfully!")